import os
import io
import csv
import time
import json
import logging
import re
import random
import shutil
import glob
import collections
import subprocess as sp
from . import runtime
import iproc.executors as executors
import iproc.commons as commons

logger = logging.getLogger(__name__)
# maintenance note: all states in https://slurm.schedmd.com/sacct.html should be accounted for 
# non-failed states are comments.
FAILED_STATES = {
    'BOOT_FAIL', 
    'CANCELLED', # Job was explicitly cancelled by the user or system administrator. The job may or may not have been initiated.
    # COMPLETED
    'DEADLINE',
    'FAILED', # Job terminated with non-zero exit code or other failure condition.
    'NODE_FAIL', # Job terminated due to failure of one or more allocated nodes.
    'OUT_OF_MEMORY',
    # PENDING
    'PREEMPTED', # Job terminated due to preemption.
    # RUNNING
    # REQUEUED
    # RESIZING
    # REVOKED
    # 'SUSPENDED',
    'TIMEOUT', # Job terminated upon reaching its time limit.
}
NOT_COMPLETED_STATES = {
    'PENDING',
    'RUNNING', 
    'REQUEUED', 
    'RESIZING'
}

def available():
    if executors.which('sbatch'):
        return True
    return False

def submit(job, time, mem, cpu=1, partition='ncf', nodelist=None, exclude=None, parent=None, **kwargs):
    '''
    Given a JobSpec, submit the job. 
    '''

    stepname = os.path.basename(job.cmd[0])
    # %N completes to hostname, %j to job in slurmland
    stdout = job.logfile_base +'_%N_%j.out'
    stderr = job.logfile_base +'_%N_%j.err'
    sbatch_cmd = [
        'sbatch', '--parsable',
        '--partition', partition,
        '--job-name', stepname,
        '--time', time,
        '--mem', mem,
        '-c', str(cpu),
        '-o', stdout,
        '-e', stderr
    ]
    if nodelist:
        sbatch_cmd.extend(['--nodelist', nodelist])
    if exclude:
        sbatch_cmd.extend(['--exclude', exclude])
    if parent:
        sbatch_cmd.extend(['--dependency', 'afterok:{JID}'.format(JID=parent)])
        logger.debug('parent is {}'.format(parent))
    if kwargs:
        # used for the sbatch_args command line function in iProc.py
        for arg in list(kwargs.values()):
            sbatch_cmd.append(arg)
        
    sbatch_cmd.extend(job.cmd)
    logger.debug('submitting {0}'.format(sp.list2cmdline(sbatch_cmd)))
    if job.skip:
        logger.debug('skipped job:')
        logger.debug(job)
        return commons.skipped_job
    elif job.dummy:
        logger.debug(sbatch_cmd)
        return 'dummy_{}'.format(random.randint(0,9999))
    else:
        jobid = commons.check_output(sbatch_cmd)
    logger.debug('jobid is {0}'.format(jobid))
    job.stdout = job.logfile_base +'*_{}.out'.format(jobid)
    job.stderr = job.logfile_base +'*_{}.err'.format(jobid)
    return jobid
           
def collect(jobs, polling_interval=5, cancel_on_fail=True):
    '''
    This function will block until a Slurm job fails, where it will throw an error
    or return, if all slurm jobs exit successfully. (deprecated)

    :param jobs: Dict of { job id: jobspec as described in common }
    :type jobs: dict
    :param polling interval: Polling interval in minutes
    :type polling_interval: int
    :param cancel_on_fail: Cancel jobs on failure
    :type cancel_on_fail: bool
    '''
    time.sleep(1 * polling_interval)
    while True:
        pval = __poll(jobs, cancel_on_fail)
        if pval:
            break
        time.sleep(60 * polling_interval)
    # print job profiling informtion
    job_profiles = profile(list(jobs.keys()))
    logger.debug('job profile\n%s', job_profiles)
    return True

def _sacct_state_query(job_ids):
    
    if not job_ids:
        return {}
    def sacct(job_ids):
        sacct_list = [
        'sacct', 
        '--noheader',
        '--parsable2',
        '--allocations',
        '--jobs', ','.join(job_ids),
        '--format', 'State'
        ]
        logger.debug(sacct_list)
        return sacct_list
    try:
        sacct_output = commons.check_output(sacct(job_ids)).strip('\n')
        job_state_list = sacct_output.split('\n')
        logger.debug(job_state_list)
    except sp.CalledProcessError as e:
        logger.debug('Sacct Error')
        logger.info(e)
        job_state_list = []
        
    if len(job_state_list) == len(job_ids):
        job_states = dict(list(zip(job_ids, job_state_list)))
    else:
        job_states={}
        #we need to go one at a time, because slurm has not returned all jobids 
        #therefore, results could be in any order
        for job in job_ids:
            sacct_cmd = sacct([job])
            job_state = commons.check_output(sacct_cmd).strip('\n')
            logger.debug(job_state)
            job_states[job] = job_state

    logger.debug(job_states)
    return job_states

def __poll(jobs, cancel_on_fail=True):
    returned_jobs = poll_count(jobs,cancel_on_fail)
    joblimit = len(jobs)
    if returned_jobs == joblimit:
        #all jobs have returned
        return True
    elif return_jobs < joblimit:
        # not all jobs have returned
        return False
    else: #return_jobs > joblimit. Not good
        raise Exception

def poll_count(jobs, cancel_on_fail=True):
    ''' poll a list of generic job ids and return the number of finished jobs '''
    job_ids = list(jobs.keys())
    dummy_vals = [job.dummy for job in list(jobs.values())] 
    if any(dummy_vals):
        if not all(dummy_vals):
            #paranoid, but just in case
            for job in jobs:
                logger.debug(job)
            raise ValueError('Only some jobs were marked dummy jobs, but this should be all or nothing.')
        else:
            return len(jobs)

    job_ids = sorted(job_ids,key=int)
    job_states = _sacct_state_query(job_ids)
    logger.debug('job states are\n' + json.dumps(job_states, indent=2))
    # iterate over each polled job state to check for failure
    failed_jobs = []
    for job_id,job_state in list(job_states.items()):
        # update state of job object
        job_obj = jobs[job_id] 
        # iterate over all known FAILED states
        for failed_state in FAILED_STATES:
            # check if any job is in a FAILED state
            if failed_state in job_state:
                failed_jobs.append(job_obj)

    # check completion and update job state
    finished_job_count=0
    for job_id,job_state in list(job_states.items()):
        job = jobs[job_id]
        if job.state == 'COMPLETED':
            # was this job previously marked as completed? then skip
            finished_job_count += 1
            continue
        incomplete_flag=False 
        for incomplete_state in NOT_COMPLETED_STATES:
            if incomplete_state in job_state:
                logger.debug('job not completed yet %s', job_id)
                incomplete_flag = True
        if incomplete_flag:
                # keep going on to the next job
                continue
        if 'COMPLETED' in job_state or job_state in FAILED_STATES:
            # convert glob to actual filename.
            # could replace star with host job ran on, as job is now in sacct
            errlist = glob.glob(job.stderr)
            if len(errlist) != 1:
                # wait a minute, then retry one last time
                time.sleep(1*60)
                errlist = glob.glob(job.stderr)
                if len(errlist) > 1:
                    logger.error(errlist)
                    logger.error(job.stderr)
                    raise IOError
                elif len(errlist)==0 :
                    logger.error(job.stderr)
                    if job_state == 'CANCELLED':
                        # probably autocanceled dependent job
                        continue
                    else:
                        logger.error(job.stderr)
                        logger.error(job_state)
                        raise IOError
            job.stderr = errlist[0]
            outlist = glob.glob(job.stdout)
            if len(outlist) != 1:
                # wait ten minutes, then retry one last time
                time.sleep(10*60)
                outlist = glob.glob(job.stdout)
                if len(outlist) != 1:
                    logger.error(outlist)
                    logger.error(job.stdout)
                    raise IOError
            job.stdout = outlist[0]
        if 'COMPLETED' in job_state:
            finished_job_count += 1
        # set object's state to state from query
        job.state = job_state

    if failed_jobs:
        job_profiles = profile(job_ids)
        logger.debug('job profile\n%s', job_profiles)
        logger.warning('performing autocancel...')
        scancel_cmd = ['scancel'] + job_ids
        commons.check_output(scancel_cmd)
        loglist = ['slurm jobs have failed']
        for job in failed_jobs:
            err = job.stderr
            out = job.stdout
            loglist.append('{} job, logs at:'.format(job.state))
            loglist.append('{} {}'.format(err,out))
        if cancel_on_fail:
            message = '\n'.join(loglist) 
            raise commons.FailedJobError(message)
        else:
            logger.warning('to cancel jobs, run scancel '+' '.join(str(x) for x in job_ids))
    else:
        return finished_job_count

def profile(job_ids):
    ''' get profiling information for a list of job ids '''
    if not job_ids:
        return 'no jobids to profile'
    # fixes python 2 > 3 bug for dict.keys() and similar
    job_ids = list(job_ids)
    if 'dummy' in job_ids[0]:
        return 'dummy run, no profiling to show'
    job_ids_str = ','.join(job_ids)
    cmd = [
        'sacct',
        '-j', job_ids_str,
        '--format=JobID,JobName,State,Partition,nodelist,MaxRSS,MaxVMSize,AveRSS,AveVMSize,Elapsed,TotalCPU'
    ]
    stdout = commons.check_output(cmd)
    return stdout

if __name__ == '__main__':
    # quick test
    job_profiles = profile(['53809421','53809482','53809160','53809360','53809612'])
    print(job_profiles)

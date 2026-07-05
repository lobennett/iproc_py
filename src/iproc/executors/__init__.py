import os
import sys
import pkgutil
import importlib
import time
import logging
from iproc.commons import which
import iproc.commons as commons

current_module = sys.modules[__name__]
logger = logging.getLogger(__name__)

def get(name=None):
    if name:
       return importlib.import_module('.' + name, 'iproc.executors')
    return _detect_scheduler()

def _detect_scheduler():
    for loader, modname, ispkg in pkgutil.iter_modules(current_module.__path__):
        module = loader.find_module(modname).load_module(modname)
        if module.__name__ == '__version__':
            continue
        elif module.available():
            return module
    raise SchedulerNotFoundError('no scheduler was found on this system')

def wait_for_finished_job(executor,jobs,cancel_on_fail,polling_interval,jobs_to_wait_for):
    ''' polls jobs in 'jobs' dict(ID:jobSpec), 
    returns the number of finished jobs when job count exceeds jobs_to_wait_for.
    waits for the specified number of minutes in between polling attempts.
    '''
    while True:
        finished_job_count = executor.poll_count(jobs, cancel_on_fail)
        if finished_job_count < jobs_to_wait_for: 
            time.sleep(60 * polling_interval)
            continue
        else:
            return finished_job_count

def afterok_submit(executor, job, **kwargs):
    '''submits jobid, then adds jobid to jobs that depend on it in the job
    queue, from the 'afterok' structure, and returns jobid or sentinel object
    on successful completion'''

    try:
        jobid = executor.submit(job, **kwargs)
    except Exception as e:
        logger.debug(vars(job))
        raise e
    if job.afterok:
       for dependent_pair in job.afterok: 
            dependent_job,afterok_kwargs = dependent_pair
            if not jobid == commons.skipped_job:
                afterok_kwargs['parent'] = jobid 
            else:
                logger.debug('parent already ran, not assigning jobid value to parent key') 
            # dependent job will have been added to jobspeclist after parent, so this is all we need to do
    return jobid 

def rolling_submit(executor,jobspec_list, job_limit=float('inf'), polling_interval=5, cancel_on_fail=True):
    '''
    takes in a list of jobs and makes sure that there are always as many jobs
    running as there can be
    :param jobspec_dict: Dict of {jobspec as described in common:kwargs for slurm}
    :type jobs: dict
    :param job_limit : Maximum number of jobs submitted to slurm at once
    :type polling_interval: int or inf
    :param polling interval: Polling interval in minutes
    :type polling_interval: int
    :param cancel_on_fail: Cancel jobs on failure
    :type cancel_on_fail: bool
    '''
    number_of_jobs = len(jobspec_list)
    if number_of_jobs < job_limit:
        job_limit = number_of_jobs
    active_job_count = 0 
    old_total_finished = 0
    jobs={}
    while jobspec_list:
        if active_job_count < job_limit :
            job_spec,kwargs = jobspec_list.pop(0)
            jid = afterok_submit(executor, job_spec, **kwargs)
            if jid == commons.skipped_job:
                logger.info('jid == skipped job')
                continue
            active_job_count += 1
            jobs[jid] = (job_spec) 
        else:
            #want to let one additional job finish
            jobs_to_wait_for=old_total_finished+1
            logger.info('waiting for {} jobs to be done'.format(jobs_to_wait_for))
            total_finished_jobs = wait_for_finished_job(executor,jobs, cancel_on_fail,polling_interval,jobs_to_wait_for)
            newly_finished_job_count = total_finished_jobs - old_total_finished 
            active_job_count -= newly_finished_job_count
            old_total_finished = total_finished_jobs
            logger.debug('{} just finished'.format(newly_finished_job_count))
            logger.debug('{} finished in total'.format(total_finished_jobs))
            logger.debug('{} active jobs'.format(active_job_count))
    final_jobs_to_wait_for = old_total_finished + active_job_count
    assert(final_jobs_to_wait_for <= number_of_jobs)
    wait_for_finished_job(executor, jobs,cancel_on_fail,polling_interval,jobs_to_wait_for=final_jobs_to_wait_for) 
    # print job profiling information, only available in slurm right now
    job_profiles = executor.profile(list(jobs.keys()))
    logger.debug('job profile\n%s', job_profiles)
    return True

class SchedulerNotFoundError(Exception):
    pass



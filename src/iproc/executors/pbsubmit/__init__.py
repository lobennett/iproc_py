import os
import re
import time
import logging
import paramiko
import getpass as gp
import subprocess as sp
import collections as col
import iproc.commons as commons
import xml.etree.ElementTree as et
from . import runtime
import iproc.executors as executors

logger = logging.getLogger(__name__)

JobState = col.namedtuple('JobState', ['pid', 'state', 'stdout', 'stderr', 'returncode'])
Process = col.namedtuple('Process', ['pid', 'pbsjob'])

def available():
    if executors.which('pbsubmit'):
        return True
    return False

class State:
    RUNNING = (
        'Q',    # queued
        'R',    # running
        'H',    # held
        'E'     # exited
    )
    NOT_RUNNING = (
        'C',    # complete
    )

def submit(job, **kwargs):
    '''
    Given a JobSpec, submit the job. You can pass in other abstract keyword 
    arguments including 'memory', 'stdout', 'stderr', and 'job_name'. These 
    These will be translated into their respective PBS arguments.
    '''
    args,_ = __parse_arguments(**kwargs)
    pbsubmit = commons.which('pbsubmit')
    assert(pbsubmit)
    cmd = [pbsubmit]
    cmd.extend(args)
    command = job.cmd
    if isinstance(command, list):
        command = sp.list2cmdline(command)
    cmd.extend(['-c', command])
    logger.debug('job submission command is: %s', cmd)
    if job.skip:
        return commons.skipped_job
    elif job.dummy:
        logger.debug(cmd)
        return 'dummy_{}'.format(random.randint(0,9999))
    else:
        output = commons.check_output(cmd, stderr=sp.STDOUT).strip().split('\n')
    pbsjob = re.match('^Opening pbsjob_(\d+)', output[0]).groups(0)[0]
    jobid = output[-1]
    proc = Process(pid=jobid, pbsjob=int(pbsjob))
    logger.info('scheduler process is {0}'.format(proc))
    return proc

def collect(jobs, polling_interval=1, cancel_on_fail=True):
    '''
    Given a list of JobSpec, continuously poll for their JobState at 
    polling_interval minutes. If cance_on_fail is True, cancel all 
    jobs if any job is in a failed state. (deprecated)
    '''
    if polling_interval > 2:
        raise PollingError('PBS will forget completed jobs much faster than your polling interval')
    procs = set(jobs.keys())
    completed = set()
    while True:
        running = False
        # only check pids that are not completed
        check = procs.difference(completed)
        logger.debug('checking %s', [proc.pid for proc in check])
        # poll for states
        states = __poll(check)
        for proc,state in iter(list(states.items())):
            if state.state is State.NOT_RUNNING:
                completed.add(proc)
                # check if job exited erroneously
                if state.returncode > 0:
                    logger.warn('job %s has failed with returncode %s', state.pid, state.returncode)
                    # cancel all remaining jobs
                    if cancel_on_fail:
                        cancel_procs = procs.difference(completed)
                        logger.debug('cancelling remaining jobs %s', [proc.pid for proc in cancel_procs])
                        cancel(cancel_procs)
                    raise commons.FailedJobError('pbs job {} has failed'.format(proc))
        if not check:
            break
        time.sleep(60 * float(polling_interval))

def poll_count(jobs,cancel_on_fail=True):
    ''' poll a list of qstat proc objects and return the number of finished jobs '''
    if list(jobs.values())[0].dummy:
        return len(jobs)
    procs = set(jobs.keys())
    completed = set()
    logger.debug('checking %s', [proc.pid for proc in procs])
    # poll for states
    states = __poll(procs)
    for proc,state in iter(list(states.items())):
        if state.state is State.NOT_RUNNING:
            completed.add(proc)
            # check if job exited erroneously
            if state.returncode > 0:
                logger.warn('job %s has failed with returncode %s', state.pid, state.returncode)
                # cancel all remaining jobs
                if cancel_on_fail:
                    cancel_procs = procs.difference(completed)
                    logger.debug('cancelling remaining jobs %s', [proc.pid for proc in cancel_procs])
                    cancel(cancel_procs)
                raise commons.FailedJobError('pbs job {} has failed'.format(proc))
            else: #success! Mark job as completed
                jobs[proc].state = 'COMPLETED'
    # all procs checked, return number of completed jobs
    return len(completed) 

class PollingError(Exception):
    pass

def cancel(procs):
    '''
    Call qdel on a list of processes. We need to call qdel multiple 
    times because if a Job is in a [C]ompleted or Unknown state, qdel 
    will abort and may not cancel any of the jobs.
    '''
    qdel = commons.which('qdel')
    assert(qdel)
    for proc in procs:
        cmd = [qdel, proc.pid]
        try:
            logger.debug('qdel command is: %s', sp.list2cmdline(cmd))
            commons.check_output(cmd, stderr=sp.PIPE)
        except sp.CalledProcessError as e:
            # qdel will return a 170 exit status if it tries to query the 
            # state of a Job ID that is already in a 'C' state, or a 170 
            # exit status if the Job ID is unknown. We should pass on either
            # of these states. A Job ID can become unknown only minutes after 
            # a job has entered the 'C' state.
            if e.returncode == 153:
                logger.debug('job %s is in a completed state and cannot be cancelled', proc.pid)
                pass
            elif e.returncode == 170:
                logger.debug('job %s is unknown and cannot be cancelled', proc.pid)
                pass
            else:
                raise e

def __poll(procs):
    '''
    Given a list of Job IDs, run qstat on each and return a dictionary
    of Job IDs and a JobState.
    '''
    states = dict()
    for proc in procs:
        states[proc] = __qstat(proc)
    return states

def __jobinfo(proc, node='launchpad'):
    '''
    Qstat quickly forgets about jobs but there is a `jobinfo' command
    available on the master node which can see further into the past.
    '''
    cmd = [
        'jobinfo',
        proc.pid
    ]
    username = gp.getuser()
    # ssh into head node to get job info
    logging.getLogger('paramiko').setLevel(logging.INFO)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(node)
    logger.debug('jobinfo command %s', cmd)
    _,stdout,_ = client.exec_command(sp.list2cmdline(cmd))
    stdout = stdout.read()
    client.close()
    # get job pid without domain  
    match = re.match('^(\d+)\.', proc.pid)
    pid = match.group(1)
    # parse exit status
    stdout = stdout.strip().split('\n')
    match = re.match('^\s+Exit status: (\d+)$', stdout[-1])
    exit_status = match.group(1)
    # build XML output similar to qstat -x
    root = et.Element('jobinfo')
    et.SubElement(root, 'job_state').text = 'C'
    et.SubElement(root, 'exit_status').text = exit_status
    et.SubElement(root, 'Output_Path').text = '/pbs/{0}/pbsjob_{1}.o{2}'.format(username, proc.pbsjob, pid)
    et.SubElement(root, 'Error_Path').text = '/pbs/{0}/pbsjob_{1}.e{2}'.format(username, proc.pbsjob, pid)
    return et.tostring(root)

def __qstat(proc):
    '''
    Run the PBS qstat command on a Job ID and return a JobState.
    '''
    qstat = commons.which('qstat')
    assert(qstat)
    cmd = [
        qstat,
        '-x',
        '-f',
        proc.pid
    ]
    logger.debug('qstat command {0}'.format(cmd))
    try:
        output = commons.check_output(cmd)
    except sp.CalledProcessError as e:
        if e.returncode == 153:
            logger.debug("job %s is in a completed state, trying jobinfo", proc.pid)
            output = __jobinfo(proc)
        elif e.returncode == 170:
            logger.debug("job %s is unknown to the scheduler, trying jobinfo", proc.pid)
            output = __jobinfo(proc)
        else:
            raise e
    xml = et.fromstring(output.strip())
    job_state = xml.findtext('.//job_state')
    exit_status = xml.findtext('.//exit_status')
    output_path = re.sub('^.*:', '', xml.findtext('.//Output_Path'))
    error_path = re.sub('^.*:', '', xml.findtext('.//Error_Path'))
    logger.debug('pid {0} is in {1} state'.format(proc.pid, job_state))
    if job_state in State.RUNNING:
        return JobState(pid=proc.pid, state=State.RUNNING, 
                        stdout=None, stderr=None, 
                        returncode=exit_status)
    elif job_state in State.NOT_RUNNING:
        stdout,stderr = None,None
        if os.path.exists(output_path):
            with open(output_path, 'rb') as fo:
                stdout = fo.read().strip()
        if os.path.exists(error_path):
            with open(error_path, 'rb') as fo:
                stderr = fo.read().strip()
        return JobState(pid=proc.pid, state=State.NOT_RUNNING, 
                        stdout=stdout, stderr=stderr, 
                        returncode=int(exit_status))

class QstatError(Exception):
    pass

def __parse_arguments(**kwargs):
    ''' 
    Parse abstract keyword arguments including 'memory', 'stdout', 'stderr', 
    and 'job_name' and translate them into valid qsub arguments e.g., 'vmem',
    '-O', '-E', '--job-name', etc.
    '''
    required = ['queue']
    unrecognized = list()
    arguments = list()
    qsub_opts = {
        'nodes': 1,
        'ppn': 1,
        'vmem': '1gb'
    }
    for key,value in iter(list(kwargs.items())):
        if key in ['partition', 'queue'] and value:
            arguments.extend(['-q', value])
            required.remove('queue')
            continue
        elif key in ['memory', 'mem'] and value:
            _value = __parse_mem_value(value)
            qsub_opts['vmem'] = __parse_mem_value(value)
            continue
        elif key == 'stdout' and value:
            arguments.extend(['-O', os.path.expanduser(value)])
            continue
        elif key == 'stderr' and value:
            arguments.extend(['-E', os.path.expanduser(value)])
            continue
        elif key == 'job_name' and value:
            arguments.extend(['--job-name', value])
            continue
        elif key == 'parent' and value:
            arguments.extend(['-W', 'depend=afterok:{JID}'.format(JID=value)])
            continue
        elif key == 'cpu' and value:
            qsub_opts['ppn'] = int(value)
            continue
        unrecognized.append(key)
    qsub_opt = 'nodes={0}:ppn={1},vmem={2}'.format(qsub_opts['nodes'],
                                                   qsub_opts['ppn'],
                                                   qsub_opts['vmem'])
    arguments.extend(['-l', qsub_opt])
    if required:
        raise RequiredArgumentsError('required arguments are missing {0}'.format(required))
    return arguments,unrecognized

class RequiredArgumentsError(Exception):
    pass

def __parse_mem_value(m):
    '''
    Helper function used to parse an abstract memory string into a valid PBS 
    argument:

    1K or 1KB = 1kb
    1M or 1MB = 1mb
    1G or 1GB = 1gb
    1T or 1TB = 1tb
    '''
    try:
        match = re.match('^(\d+)(K|KB|M|MB|G|GB|T|TB)$', m)
        size,unit = match.group(1),match.group(2)
    except:
        raise MemoryArgumentError('failed to understand {0}'.format(m))
    if unit in ('K', 'KB'):
        unit = 'kb'
    elif unit in ('M', 'MB'):
        unit = 'mb'
    elif unit in ('G', 'GB'):
        unit = 'gb'
    elif unit in ('T', 'TB'):
        unit = 'tb'
    memarg = size + unit
    logger.debug('translated memory argument will be %s', memarg)
    return size + unit

def profile(job_ids):
    ''' get profiling info for a list of job IDs. Not functional'''
    return 'profiling not available for Qstat'

class MemoryArgumentError(Exception):
    pass


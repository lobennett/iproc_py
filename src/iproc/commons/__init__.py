import os
import time
import shutil
import shlex
import socket
import atexit
import signal
import logging
import hashlib
import pickle
import json
import subprocess as sp
import collections as col

logger = logging.getLogger(__name__)

Program = col.namedtuple('Program', [
    'file', 
    'base', 
    'root', 
    'ext', 
    'dir', 
    'md5', 
    'args'
])

Summary = col.namedtuple("Summary", ["launcher", "pid", "stdout", "stderr", 
                                     "status", "env", "command"])

Machine = col.namedtuple('Machine', [
    'hostname'
])

skipped_job = object()

## cribbed from pylib 6.6.0
def expand(f, links=True, evars=True):
    '''
    Expand a file or directory name completely.

    Example::
        >>> from pylib.fun import expand
        >>> expand("~/sym/link/$DIR", links=True, evars=True)
        '/home/user/real/path'
    
    :param f: File name
    :type f: str
    :param links: Resolve symbolic links
    :type links: bool
    :param evars: Resolve environment variables
    :type evars: bool
    :returns: Expanded file or directory name
    :rtype: str
    '''
    # resolve environment variables
    if evars:
        f = os.path.expandvars(f)
    # resolve symbolic links
    if links:
        f = os.path.realpath(os.path.expanduser(f))
    else:
        f = os.path.abspath(os.path.expanduser(f))
    return f

def execute(command, kill=False):
    '''
    Simple(r) function to execute a command.

    :param command: Command
    :type command: str|list
    :param kill: Raise exception if the subprocess returncode is non-zero
    :type kill: bool
    :return: Summary of 'stdout', 'stderr', 'status', 'env', and 'command'
    :rtype: :mod:`pylib.fun.Summary`
    '''
    # split command, if necessary
    if isinstance(command, str):
        com = shlex.split(command)
    else:
        com = command
    logger.debug("executing command %s", com)
    # execute subprocess
    p = sp.Popen(com, stdout=sp.PIPE, stderr=sp.PIPE)
    (stdout, stderr) = p.communicate()
    # get exit status
    status = p.returncode
    # get stdout and stderr
    if(stdout.strip() == ""):
        stdout = None
    else:
        stdout = stdout.strip()
    if(stderr.strip() == ""):
        stderr = None
    else:
        stderr = stderr.strip()
    # pull the environment together as a giant string
    env_str = ""
    for k,v in iter(list(os.environ.items())):
        env_str += "%s => %s\n" % (k,v)
    # return command summary
    summary = Summary(launcher=None, stdout=stdout, stderr=stderr, status=status,
            command=command, env=env_str, pid=p.pid)
    # check process status and kill program
    if kill:    
        __checksummary(summary)
    return summary

def __checksummary(summary):
    '''
    Check command execution summary and exit program if status is non-zero.

    :param summary: Job summary
    :type summary: :mod:`pylib.fun.Summary`
    '''
    if summary.status != 0:
        msg = "command failed: %s (%s)\n" % (summary.command, summary.status)
        if summary.stdout:
            msg += "[stdout]\n%s\n" % summary.stdout
        if summary.stderr:
            msg += "[stderr]\n%s\n" % summary.stderr
        raise NonZeroError(msg)

class NonZeroError(Exception):
    pass


def program(argv):
    '''
    Get program information.

    :param argv: Tokenized command
    :type argv: list
    :returns: Program tuple 
    :rtype: :mod:`iproc.commons.Program`
    '''
    fullfile = os.path.abspath(argv[0])
    dirname = os.path.dirname(fullfile)
    basename = os.path.basename(fullfile)
    root,ext = os.path.splitext(basename)
    md5sum = md5file(fullfile)
    args = []
    if len(argv) > 1:
        args = argv[1:]
    return Program(file=fullfile, base=basename, root=root, ext=ext, 
                   dir=dirname, md5=md5sum, args=args)

def machine():
    '''
    Get machine information.

    :returns: Machine
    :rtype: :mod:`iproc.commons.Machine`
    '''
    hostname = socket.gethostname()
    return Machine(hostname=hostname)

def md5file(f):
    '''
    Get the md5sum of a file

    :param f: Filename
    :type f: str
    :returns: hex digest
    :rtype: str
    '''
    with open(os.path.expanduser(f), 'rb') as fo:
        return hashlib.md5(fo.read()).hexdigest()

def which(x):
    '''
    Silimar to bash which command

    :param x: Command to find
    :type x: str
    :returns: path to command
    :rtype: str
    '''
    for p in os.environ.get("PATH").split(os.pathsep):
        p = os.path.join(p, x)
        if os.path.exists(p):
            return os.path.abspath(p)
    return None

## end cribbed from pylib fun

def move_on_exit(source, dest):
    # a closure to copy and remove output directory on atexit
    # Note that this will not be able to access files stored on nodes during slurm jobs.
    def _atexit_handler(*args):
        if (source and dest) and os.path.exists(source) and (source != dest):
            timestamp = str(int(time.time()))
            destname = os.path.join(dest, 'crash.iproc.{0}'.format(timestamp))
            logger.info('copying %s to %s [atexit]', source, destname)
            shutil.copytree(source, destname)
            logger.info('removing %s [atexit]', source)
            shutil.rmtree(source)
    # closure to remove output directory on SIGTERM
    def _sigterm_handler(*args):
        if os.path.exists(source):
            logger.info('purging terminated job data in %s', source)
            shutil.rmtree(source)
            exit(130)
    # register handlers (note that signal.signal will trigger an atexit)
    atexit.register(_atexit_handler)
    signal.signal(signal.SIGINT, _sigterm_handler)

def save_finished(self):
    filename=self.fname+'.finished'
    _pickle_file(filename)

def save_crash(a1,a2,a3):
    logger.debug(a1)
    logger.debug(a2)
    logger.debug(a3)
    filename=self.fname+'.crash'
    self._pickle_file(filename)
    exit(130)

def _pickle_file(self,filename):
    with open(filename,'wb') as f:
        pickle.dump(self.obj,f)    

def check_output(cmd, accept_fail=False, **kwargs):
    try: 
        returnval = sp.check_output(cmd, stderr=sp.STDOUT, **kwargs).strip()
        return returnval.decode()
    except sp.CalledProcessError as e:
        logger.info(e.output)
        if accept_fail:
            return returnval.decode()
        else:
            raise e

def capture_err(cmd):
    ''' returns output of process, regardless of whether or not there is an error'''
    returnval = sp.run(cmd,capture_output=True)
    return returnval 

def check_call(cmd, stdout=None, stderr=None):
    try: 
        returnval = sp.check_call(cmd, stdout=stdout, stderr=stderr)
    except sp.CalledProcessError as e:
        logger.info(e.output)
        logger.exception(e)
        raise e

def get_json_entity(json_fname,entity_name):
    with open(json_fname) as f:
        try:
            j = json.load(f)
        except:
            logger.error('problem with json {}'.format(json_fname))
            raise
        try:
            entity_value = j[entity_name]
        except KeyError:
            logger.error('Make sure {} field is populated for file {}'.format(entity_name,json_fname))
            raise
    return entity_value

class ScriptBuilder():
    #This allows for more flexible creation of sbatch scripts for 
    #non-computational steps, while maintaing provenance info
    # and compatibility with existing slurm engine.
    # the intended use is to append lines to a script, and then 
    #when you are ready to run, finalize and create a jobspec similar
    # to that which is created by steps.py functions .
    # The created script will have no arguments.
    def __init__(self,script_location):
        self.header = ['#!/bin/bash\n', 'set -xeou pipefail\n']
        self.fname = script_location
        
    def append(self, cmd):
        # add line to script. Context-manage each time.
        with open(self.fname, 'a') as f:
            cmd_newline = cmd + ['\n']
            cmdline = ' '.join(cmd_newline)
            f.write(cmdline)
            
    def blank_file(self):
        try:
            with open(self.fname, 'w') as f:
                f.writelines(self.header)
        except (OSError,IOError):
            #create empty file
            open(self.fname, 'a').close()
        os.chmod(self.fname, 0o755)

    def check_header(self):
        try:
            with open(self.fname, 'r') as f:
                first_two_lines = f.readlines()[0:2]
                assert(first_two_lines == self.header)
        except (OSError,IOError):
            # file doesn't exist. Let's create a file with the right header.
            with open(self.fname, 'w') as f:
                f.writelines(self.header)
            os.chmod(self.fname, 0o755)
        except AssertionError:
            raise Exception('first two lines of {} do not match standard template'.format(self.fname))
        
class FailedJobError(Exception):
    pass

class CommandNotFound(Exception):
    pass

class JobSpec(object):
    '''
    helper class for job constructor
    used to contain all the information the executor needs to run a job, 
    and that is needed for pre-and post-processing.
    '''
    def __init__(self, cmd,logfile_base,outfiles,rmfiles=None):
        self.cmd = cmd
        self.logfile_base = logfile_base
        self.outfiles = outfiles
        self.rmfiles = rmfiles
        # these should be set upon execution
        self.stderr = None
        self.stdout = None
        self.state = None 
        # get set of all outdirs automatically
        outfile_dirs = {os.path.dirname(f) for f in outfiles}  
        self.outfile_dirs = {os.path.join(d,'logs/') for d in outfile_dirs}
        self.afterok = [] # to be filled with other jobspecs #jobception
        self.skip = False 
        self.dummy = False 

    def prepend_cmd(self, prefix):
        self.cmd =  prefix + self.cmd 

import os

def cpus_per_node():
    if not os.environ.get('SLURM_CPUS_PER_TASK', None):
        raise RuntimeError('SLURM_CPUS_PER_TASK variable is missing or null')
    return int(os.environ['SLURM_CPUS_PER_TASK'])

class RuntimeError(Exception):
    pass

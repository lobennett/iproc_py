import os

def cpus_per_node():
    if not os.environ.get('PBS_NUM_PPN', None):
        raise RuntimeError('PBS_NUM_PPN variable is missing or null')
    return int(os.environ['PBS_NUM_PPN'])

class RuntimeError(Exception):
    pass

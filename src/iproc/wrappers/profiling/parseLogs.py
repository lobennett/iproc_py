#!/usr/bin/env python
'''
This script is intended to crawl through the logs of an iproc run that has been completed using a wrapper.
The wrapper is expected to dump output to either slurm.err or slurm.out files.
Each class reads through all this output and extracts the usable data.
This data can then be analyzed in the main function, using the helper functions.
'''

import re
import glob
import os
import subprocess
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from texttable import Texttable

runscript_regex='.*_[0-9]+_[a-z,A-Z,0-9]+_(.*?\.[a-z]+)'

class mountstats_parser(object):
    # designed to parse a file produced by, e.g., /usr/sbin/mountstats mountstats --since  ./checkpoint1.mst /ncf/cnl06
    #feed me slurm.out files
    def __init__(self,fname):
        self.nfs_dict={}
        f = tail(fname,'100')
        line = next(f)
        #read through lines until we get to the desired section
        while not re.match('NFS byte counts:', line):
            try:
                line = next(f)
            except StopIteration as e:
                raise(e)
        # now we're in the desired section.
        method_lines=[{'key':'read(2)','regex':'\s+applications read ([0-9]+) bytes via read\(2\)'},
        {'key':'write(2)','regex':'\s+applications wrote ([0-9]+) bytes via write\(2\)'},
        {'key':'O_DIRECT read(2)','regex':'\s+applications read ([0-9]+) bytes via O_DIRECT read\(2\)'},
        {'key':'O_DIRECT write(2)','regex':'\s+applications wrote ([0-9]+) bytes via O_DIRECT write\(2\)'},
        {'key':'NFS READ','regex':'\s+client read ([0-9]+) bytes via NFS READ'},
        {'key':'NFS WRITE','regex':'\s+client wrote ([0-9]+) bytes via NFS WRITE'}]
        for method in method_lines:
            line = next(f)
            try:
                self.nfs_dict[method['key']] = re.match(method['regex'],line).group(1)
            except Exception as e:
                print(fname)
                print(method)
                print(line)
                raise(e)

    def nfs(self,method,units='B'):
        bitshift_lookup={'GiB':30,'MiB':20,'KiB':10,'B':0}
        shift=bitshift_lookup[units]
        bytecount=int(self.nfs_dict[method])
        out_quantity = bytecount >> shift 
        return out_quantity

    def nfs_sprint(self,method,units):
        out_quantity = self.nfs(method,units)
        return '{} {} via {}'.format(out_quantity,units,method)

class verbosetime_parser(object):
    # feed me slurm.err files
    def __init__(self,fname):
        self.metrics_dict={}
        f = tail(fname,'30')
        line = next(f)
        while not re.match('\s+Command being timed:', line):
            line = next(f)
        metric_lines=[{'key':'user_time','regex':'\s+User time \(seconds\): ([0-9]+.[0-9]+)'},
        {'key':'sys_time','regex':'\s+System time \(seconds\): ([0-9]+.[0-9]+)'},
        {'key':'pct_CPU','regex':'\s+Percent of CPU this job got: ([0-9]+)%'},
        {'key':'wall_time','regex':'\s+Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([0-9]*:?[0-9]{2}:?.?[0-9]{2})'},
        {'key':'avg_shared_text','regex':'\s+Average shared text size \(kbytes\): ([0-9]+)'},
        {'key':'avg_unshared_data','regex':'\s+Average unshared data size \(kbytes\): ([0-9]+)'},
        {'key':'avg_stack_size','regex':'\s+Average stack size \(kbytes\): ([0-9]+)'}, 
        {'key':'avg_total_size','regex':'\s+Average total size \(kbytes\): ([0-9]+)'},
        {'key':'max_RSS','regex':'\s+Maximum resident set size \(kbytes\): ([0-9]+)'}, 
        {'key':'avg_RSS','regex':'\s+Average resident set size \(kbytes\): ([0-9]+)'},
        {'key':'major_pagefaults','regex':'\s+Major \(requiring I/O\) page faults: ([0-9]+)'},
        {'key':'minor_pagefaults','regex':'\s+Minor \(reclaiming a frame\) page faults: ([0-9]+)'},
        {'key':'voluntary_context_switchees','regex':'\s+Voluntary context switches: ([0-9]+)'}, 
        {'key':'involuntary_context_switches','regex':'\s+Involuntary context switches: ([0-9]+)'}, 
        {'key':'swaps','regex':'\s+Swaps: ([0-9]+)'},
        {'key':'fs_in','regex':'\s+File system inputs: ([0-9]+)'},
        {'key':'fs_out','regex':'\s+File system outputs: ([0-9]+)'},
        {'key':'socket_sent','regex':'\s+Socket messages sent: ([0-9]+)'},
        {'key':'socket_received','regex':'\s+Socket messages received: ([0-9]+)'},
        {'key':'signals_delivered','regex':'\s+Signals delivered: ([0-9]+)'},
        {'key':'page_size','regex':'\s+Page size \(bytes\): ([0-9]+)'}]

        for metric in metric_lines:
            line = next(f)
            try:
                self.metrics_dict[metric['key']] = re.match(metric['regex'],line).group(1)
            except Exception as e:
                print(fname)
                print(metric)
                print(line)
                raise(e)
            
    def metric(self,metricname,units='KiB'):
        #default is KiB for time output
        bitshift_lookup={'GiB':20,'MiB':10,'KiB':0}
        shift=bitshift_lookup[units]
        bytecount=int(self.metrics_dict[metricname])
        out_quantity = bytecount >> shift 
        return out_quantity

class du_parser(object):
    # feed me slurm.err files
    def __init__(self,fname):
        self.metrics_dict={}
        f = tail(fname,'2')
        line = next(f)
        while not re.match('.*du -s :', line):
            line = next(f)
        metric_lines=[{'key':'size_on_disk','regex':'([0-9]+)'}]

        for metric in metric_lines:
            line = next(f)
            try:
                self.metrics_dict[metric['key']] = re.match(metric['regex'],line).group(1)
            except Exception as e:
                print(fname)
                print(metric)
                print(line)
                raise(e)
            
    def metric(self,metricname,units='KiB'):
        #default is KiB for du -s output
        bitshift_lookup={'GiB':20,'MiB':10,'KiB':0}
        shift=bitshift_lookup[units]
        bytecount=int(self.metrics_dict[metricname])
        out_quantity = bytecount >> shift 
        return out_quantity
    
def boilerplate_plot(data,colors,groups):
    # Create plot
    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1, axisbg="1.0")
    
    for data, color, group in zip(data, colors, groups):
        x, y = data
        ax.scatter(x, y, alpha=0.5, c=color, edgecolors='none', label=group)
    
    plt.title('Matplot scatter plot')
    plt.legend(loc=2)
    return fig

def logdir_nfs_by_index(search_dir,units):

    files = list(filter(os.path.isfile, glob.glob(search_dir + "*.out")))
    files.sort(key=lambda x: os.path.getmtime(x))  
    nfs_write=()
    nfs_write_data = []
    for f in files:
        try:
            p=mountstats_parser(f)
            nfs_write_data.append(p.nfs('NFS WRITE',units)) 
        except StopIteration as e:
            # insert dummy value to signify missingno for now.
            nfs_write_data.append(-1)
        print('file Processed')
    nfs_write=(list(range(len(nfs_write_data))),nfs_write_data)
    print(nfs_write)
    return nfs_write

def logdir_nfs_over_thresh(search_dir,units,thresh):

    files = list(filter(os.path.isfile, glob.glob(search_dir + "*.out")))
    files.sort(key=lambda x: os.path.getmtime(x))  
    nfs_write=()
    nfs_write_data = []
    step_names = []
    for f in files:
        try:
            p=mountstats_parser(f)
            nfs_writeval = p.nfs('NFS WRITE',units)
            if nfs_writeval > thresh:
                nfs_write_data.append(nfs_writeval) 
                stepname = re.match(runscript_regex,f).group(1)
                step_names.append(stepname)
        except StopIteration as e:
            pass
        except AttributeError as e:
            print(f)
            raise
        print('file Processed')
    nfs_write=(step_names,nfs_write_data)
    print(nfs_write)
    return nfs_write

def logdir_max_rss_by_index(search_dir,units):

    files = list(filter(os.path.isfile, glob.glob(search_dir + "*.err")))
    files.sort(key=lambda x: os.path.getmtime(x))  
    max_RSS = []
    for f in files:
        try:
            p=verbosetime_parser(f)
            max_RSS.append(p.metric('max_RSS',units))
        except StopIteration as e:
            # dummy value for missing data    
            max_RSS.append(-1)
    return (list(range(len(max_RSS))),max_RSS)  

def logdir_max_rss_over_thresh(search_dir,units,thresh):

    files = list(filter(os.path.isfile, glob.glob(search_dir + "*.err")))
    files.sort(key=lambda x: os.path.getmtime(x))  
    max_RSS = []
    step_names = []
    for f in files:
        try:
            p=verbosetime_parser(f)
            maxval = p.metric('max_RSS',units)
            if maxval>thresh:
                max_RSS.append(maxval)
                stepname = re.match(runscript_regex,f).group(1)
                step_names.append(stepname)
        except StopIteration as e:
            pass
        except AttributeError as e:
            print(f)
            raise
    return (step_names,max_RSS)  

def logdir_du_by_index(search_dir,units):

    files = list(filter(os.path.isfile, glob.glob(search_dir + "*.out")))
    files.sort(key=lambda x: os.path.getmtime(x))  
    du = []
    for f in files:
        try:
            p=du_parser(f)
            du.append(p.metric('size_on_disk',units))
        except StopIteration as e:
            # dummy value for missing data    
            du.append(-1)
    return (list(range(len(du))),du)  

def logdir_du_over_thresh(search_dir,units,thresh):

    files = list(filter(os.path.isfile, glob.glob(search_dir + "*.out")))
    files.sort(key=lambda x: os.path.getmtime(x))  
    du = []
    step_names = []
    for f in files:
        try:
            p=du_parser(f)
            sizeval = p.metric('size_on_disk',units)
            if sizeval>thresh:
                stepname = re.match(runscript_regex,f).group(1)
                step_names.append(stepname)
                du.append(sizeval)
        except StopIteration as e:
            pass
        except AttributeError as e:
            print(f)
            #for now, pass
            pass 
    return (step_names,du)  
        
def tail(fname,num_lines):
    out = commons.check_output(['tail', '-n',num_lines,fname])
    for line in out.split('\n'):
        yield(line) 

if __name__ == '__main__':
    
    twenty_five_dir = ""
    thirty_dir = ""

    noScratch_twenty_five_dir = ""
    noScratch_twenty_eight_dir = ""
    noScratch_thirty_dir = ""

    twenty_five_dir = ""
    twenty_eight_dir = ""
    thirty_dir = ""

#    high_nfs_small = logdir_nfs_over_thresh(noScratch_twenty_five_dir,'MiB',500)
#    high_nfs_large = logdir_nfs_over_thresh(noScratch_thirty_dir,'MiB',500)
#    high_nfs_small_scratch = logdir_nfs_over_thresh(twenty_five_dir,'MiB',500)
#    high_nfs_large_scratch = logdir_nfs_over_thresh(thirty_dir,'MiB',500)
#    t = Texttable()
#    t._max_width = 0
#    rows = [list(x) for x in zip(high_nfs_small[0],high_nfs_small[1],high_nfs_large[1],high_nfs_small_scratch[1],high_nfs_large_scratch[1],)]
#    rows.insert(0,['Step Name','25 tp NFS_WRITE in MiB','30 tp NFS_WRITE in MiB','25 tp NFS_WRITE in MiB, w/scratch','30 tp NFS_WRITE in MiB,w/scratch'])
#    t.add_rows(rows)
#    print(t.draw())

#    high_mem_small = logdir_max_rss_over_thresh(twenty_five_dir,'MiB',500)
#    high_mem_large = logdir_max_rss_over_thresh(thirty_dir,'MiB',500)
#    t = Texttable()
#    print(dir(t))
#    t._max_width = 0
#    ratio = [x/float(y) for x,y in zip(high_mem_small[1],high_mem_large[1])]
#    coeff = [x/25 for x in high_mem_small[1]]
#    rows = [list(x) for x in zip(high_mem_small[0],high_mem_small[1],high_mem_large[1],ratio,coeff)]
#    rows.insert(0,['Step Name','25 timepoint maxRSS in MiB','30 timepoint maxRSS in MiB','25/30 maxRSS ratio','X*25 = maxRss25'])
#    t.add_rows(rows)
#    print(t.draw())

    du_small = logdir_du_over_thresh(twenty_five_dir,'MiB',500)
    du_med = logdir_du_over_thresh(twenty_eight_dir,'MiB',500)
    du_large = logdir_du_over_thresh(thirty_dir,'MiB',500)
    t = Texttable()
    print((dir(t)))
    t._max_width = 0
    ratio = [x/float(y) for x,y in zip(du_small[1],du_large[1])]
    coeff_small = [x/25 for x in du_small[1]]
    coeff_large = [x/30 for x in du_large[1]]
    rows = [list(x) for x in zip(du_small[0],du_small[1],du_large[1],ratio,coeff_small,coeff_large)]
    rows.insert(0,['Step Name','25 timepoint disk usage in MiB','30 disk usage in MiB','25/30 du ratio','(du25)/25','(du30)/30'])
    t.add_rows(rows)
    print((t.draw()))

#    small_run_nfs = digest_logdir_nfs(twenty_five_dir,'MiB')
#    large_run_nfs = digest_logdir_nfs(thirty_dir,'MiB')
#    fig = scatter_plot_twocolor(('25 timepoints','30 timepoints'),small_run_nfs,large_run_nfs)
#    plt.title('nfs writes by task image size, after scratchdir modifications')
#    plt.ylabel('MiB')
#    plt.xlabel('job # in run')
#    plt.savefig('./nfs_scratch.png')

#    small_run_mem = logdir_max_rss_by_index(twenty_five_dir,'MiB')
#    large_run_mem = logdir_max_rss_by_index(thirty_dir,'MiB')
#    fig = scatter_plot_twocolor(('25 timepoints','30 timepoints'),small_run_mem,large_run_mem)
#    plt.title('maxRSS by task image size')
#    plt.ylabel('MiB')
#    plt.xlabel('job # in run')
#    plt.savefig('./mem.png')

#    small_run_du = logdir_du_by_index(twenty_five_dir,'MiB')
#    med_run_du = logdir_du_by_index(twenty_eight_dir,'MiB')
#    large_run_du = logdir_du_by_index(thirty_dir,'MiB')
#    groups = ('25 timepoints','28 timepoints','30 timepoints')
#    data = (small_run_du,med_run_du,large_run_du)
#    colors = ('red','green','blue')
#    fig = boilerplate_plot(data,colors,groups)
#    plt.title('size on disk by task image size')
#    plt.ylabel('MiB')
#    plt.xlabel('job # in run')
#    plt.savefig('./disk3_rerun.png')

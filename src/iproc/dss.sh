#!/bin/bash
# delayed-start spooler
# This file uses uniquely-named lockfiles to establish a FIFO queue for a given queuedir.
# the goal is to make sure that each command submitted to the queue has 
# at least a $sleeptime head start. 
# Designed with dcm2nii/x in mind, which requires a lock on a config file in the 
# user's homedir during roughly the first second of runtime.
set -x
queuedir=$1
shift
sleeptime=3

# create temporary lock file to hold our place in line
lockfile=$(mktemp -p "$queuedir")
lockfile_basename=$(basename $lockfile)

#infinite loop
while :
do
    # check if lockfile is the oldest file in the directory
    oldest_file=$(ls -t "$queuedir" | tail -1)
    if [ "$oldest_file" == "$lockfile_basename" ] ; then
        
        # run command in background, so it can get a head start
        "$@" &
        bg_pid=$!
        #hold up
        sleep ${sleeptime}
        # remove placeholder from queue
        rm -f "$lockfile"
        # wait on job, return what it returns
        wait $bg_pid 
        exit $?
    else
        echo "Lockfile  ${lockfile} is not the oldest file in ${queuedir}. Sleeping for ${sleeptime} seconds and then trying again."
        sleep ${sleeptime}
    fi
done

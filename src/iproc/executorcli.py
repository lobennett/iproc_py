#!/usr/bin/env python
# This allows scripts to access the requested number of cpus in an executor-agnostic way 
import argparse as ap
import iproc.executors as executors

def main():
    parser = ap.ArgumentParser('Command line interface for iproc.executors')
    parser.add_argument('-c', '--cpus-per-node', action='store_true')
    args = parser.parse_args()

    e = executors.get()
    if args.cpus_per_node:
        print(e.runtime.cpus_per_node())

if __name__ == '__main__':
    main()

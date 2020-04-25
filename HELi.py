#!/usr/bin/env python

# import required libraries

from datetime import datetime
import elastic
import evtxengine
import projectengine
import requests, json, argparse, os, sys, re
from multiprocessing import Process, current_process, cpu_count, Manager, Value, Queue, queues
import base64

if __name__ == "__main__":

    procs = []

    # Display project banner, list configurations, and receive queue
    project = projectengine.initiate()
    queue = project['queue']
    args = project['args']

    start_datetime = datetime.now()  

    raw_input("Project initiated, press Enter to begin processing...")

    print ""
    print "### Project Starting ###"
    print ""
    evtxengine.process_project(queue, args)
    end_datetime = datetime.now()
    duration_datetime = end_datetime - start_datetime


    print ""
    print "### Project Complete ###"
    print "----------------------------------------------------------"
    print "----------------------------------------------------------"
    print "Project ended at: " + str(end_datetime)
    print "Project duration was: " + str(duration_datetime)
    print "----------------------------------------------------------"
    print "----------------------------------------------------------"
    print ""    




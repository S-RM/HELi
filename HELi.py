#!/usr/bin/env python

# import required libraries

from datetime import datetime
from lib import elastic
from lib import evtxengine
from lib import projectengine
import requests, json, argparse, os, sys, re
from multiprocessing import Process, current_process, cpu_count, Manager, Value, Queue, queues
import threading
import base64

if __name__ == "__main__":
    procs = []

    # Display project banner, list configurations, and receive queue
    project = projectengine.initiate()
    queue = project['queue']
    args = project['args']

    start_datetime = datetime.now()  

    print("")
    print("### Project Starting ###")
    print("")

    input("Press Enter to continue...")

    # TODO: Create a single dedicated process to handle web submissions and reporting
    # Form the queue!
    support_queue = Queue()
    supportproc = Process(target=elastic.core_posting_worker,args=(support_queue,),name="support")
    supportproc.start()

    process_queue = Queue()
    for eventlog in queue['files_to_process']:
        process_queue.put(eventlog)

    procs = []
    for process in range(args.cores):
        proc_name = str(process)
        proc = Process(
            target=evtxengine.process_project,
            args=(
                queue,
                support_queue,
                supportproc,
                process_queue,
                args,
            ),
            name=proc_name
        )
        procs.append(proc)
        proc.start()

    # Wait for all processes to complete
    for proc in procs:
        proc.join()

    # Once all processes are joined, we can send stop command to support core
    support_queue.put("STOP")
    supportproc.join()

    end_datetime = datetime.now()
    duration_datetime = end_datetime - start_datetime

    print("")
    print("### Project Complete ###")
    print("----------------------------------------------------------")
    print("----------------------------------------------------------")
    print("Project ended at: " + str(end_datetime))
    print("Project duration was: " + str(duration_datetime))
    print("----------------------------------------------------------")
    print("----------------------------------------------------------")
    print("")




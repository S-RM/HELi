#!/usr/bin/env python

import requests, json, argparse, os, sys, re
from multiprocessing import Process, current_process, cpu_count, Manager, Value, Queue, queues
import threading
import mmap
import base64
import time
import Evtx.Evtx as evtx, xml.etree.ElementTree as ET
from datetime import datetime
import lib.elastic as elastic
import lib.projectengine as projectengine
from evtx import PyEvtxParser


def count_records_in_batch(queue, file_path, receive_queue):

    shutdown = False
    count = 0
    while not shutdown:

        count = count + 1
        
        # Check for up to one second if we can grab some data, else exit
        try:
            chunk_offset = queue.get(True, 1)
            

        except queues.Empty:
            # Queue is most likely empty
            # Send shutdown command
            receive_queue.put("STOP")
            shutdown = True
            break

        # Set default variables
        ChunkCount = {}
        ChunkCount[chunk_offset] = {}
        chunk_record_count = 0

        # Map log file
        with open(file_path, 'rb') as log_file: 
            buffer = mmap.mmap(log_file.fileno(), 0, access=mmap.ACCESS_READ)

        Chunk = evtx.ChunkHeader(buffer, chunk_offset)
        del buffer
        records = iter(Chunk.records())
        try:
            while True:
                next(records)
                chunk_record_count = chunk_record_count + 1
        except StopIteration:
            ChunkCount[chunk_offset]['count'] = chunk_record_count

        if chunk_record_count > 0:
            receive_queue.put(ChunkCount)     

    return True
        

def parserecord(task, filename, num_items, logBufferSize, index, nodes, GlobalRecordCount, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, support_queue, token=""):

    start = task['start']
    batch = task['count']
    end = (start + batch)
    count = 0


    JSONevents = ""

    logBufferLength = 0
    count_postedrecord = 0
        
    parser = PyEvtxParser(filename)
    for record in parser.records_json():

            count = count + 1
            logBufferLength = logBufferLength + 1
            event = {}

            record = json.loads(record['data'])

            if isinstance(record['Event']['System']['EventID'], int):
                eventid = record['Event']['System']['EventID']
                record['Event']['System']['EventID'] = {}
                record['Event']['System']['EventID']['#text'] = eventid 

            # Same thing with their Data field
            try:
                if isinstance(record['Event']['EventData']['Data'], str):
                    tmp = record['Event']['EventData']['Data']
                    record['Event']['EventData']['Data'] = {}
                    record['Event']['EventData']['Data']['#text'] = tmp
            except KeyError:
                pass
            except TypeError:
                pass

            JSONevents = JSONevents + '{"index": {}}\n'
            JSONevents = JSONevents + json.dumps(record) + "\n" 

            # Dump log buffer when full
            if logBufferLength >= int(logBufferSize):
                count_postedrecord = count_postedrecord + logBufferSize
                dump_batch(JSONevents, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, support_queue, token)
                JSONevents = ""
                logBufferLength = 0

    if logBufferLength > 0:
        count_postedrecord = count_postedrecord + logBufferLength
        dump_batch(JSONevents, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, support_queue, token)
        logBufferLength = 0
        JSONevents = ""
            

def dump_batch(events, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, support_queue, token=""):
    if not debug:
        # Web requests always work better in a thread. Waiting for network latency is silly.
        support_queue.put(
                    {
                        "type":"post",
                        "data": {
                            "events": events,
                            "index": index,
                            "nodes": nodes,
                            "token": token
                        }
                    })
        
        #elastic.postToElastic(events, index, nodes, token)

    # Report process in seperate thread. Main process should continue even if there are issues.
    support_queue.put({
                    "type":"report",
                    "data": {
                        #"GlobalRecordCount": GlobalRecordCount,
                        "logBufferLength": logBufferLength,
                        "num_items": num_items,
                        #"GlobalPercentageComplete": GlobalPercentageComplete,
                        #"GlobalTiming": GlobalTiming,
                        #"TooShortToTime": TooShortToTime
                    }
    })
    
    #report_thread = threading.Thread(target=projectengine.report_progress, args=(GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime,))
    #report_thread.start()
    #report_thread.join()

def validate_log_files(file_list):

    # For a log file to be valid, it needs to have at least one
    # record, otherwise there's no point in processing it!

    bad_files = {}
    bad_files_count = 0
    new_file_list = []

    #Check to see if the evtx file is big enough to store data
    for file_path in file_list:
        new_file_list.append(file_path)

    return_data = {}
    return_data['count'] = len(new_file_list)
    return_data['files_to_process'] = []
    return_data['files_to_process'] = new_file_list
    return_data['errors'] = {}
    return_data['errors'] = bad_files

    return return_data



def process_project(queue, args):
    
    nodes = args.nodes.replace(" ", "").split(',')
    i = 0
    for file_path in queue['files_to_process']:
        print("")
        print("### File " + str(i + 1) + " of " + str(queue['count']) + ": " + file_path)
        start_time = datetime.now()
        print("### " + str(start_time))
        print("")
        
        # First, lets instantiate the EVTX object
        evtxObject = evtx.Evtx(file_path)

        # Get first chunk header 
        total_records = 0
        with evtxObject as log:
            chunks = iter(log.chunks())
            fh = log.get_file_header()
            # Get last record number
            last_chunk_number = fh.chunk_count()
            last = fh.next_record_number() - 1

            # Get first record (oldest chunk)
            oldest = fh.oldest_chunk() + 1
            count = 0
            while True:
                chunk = next(chunks)
                count = count + 1
                if count == oldest:
                    first = chunk.log_first_record_number()
                    break

        total_records = (last - first) + 1 

        if total_records == 0:
            print("No logs in file, skipping...")
            i = i + 1
            continue
        
        # We need to calculate how many records to assign to each process
        record_batch = (total_records // args.cores)
        remainder = total_records - (record_batch * args.cores)
        store_remainder = remainder

        # If record_batch is not zero, there is at least one record per task
        Tasks = {}
        start = 0

        if record_batch > 0:

            for task in range(args.cores):
                if remainder > 0:
                    task_batch = record_batch + 1
                    remainder = remainder - 1
                else:
                    task_batch = record_batch
                Tasks[task] = {}
                Tasks[task]['count'] = task_batch
                Tasks[task]['start'] = start
                start = start + task_batch

        # We should have already caught and removed log files with < 1 records in total
        else:
            # There is less than 1 record per task
            for task in range(args.cores):
                if remainder > 0:
                    task_batch = record_batch + 1
                    remainder = remainder - 1
                else:
                    task_batch = 0
                Tasks[task] = {}
                Tasks[task]['count'] = task_batch
                Tasks[task]['start'] = start
                start = start + task_batch

        print("There are " + str(total_records) + " logs in total.")
        print("Allocating " + str(record_batch) + " logs per process with " + str(store_remainder) + " remainder.")

        procs = []
        proc = []
        # We need some variables to store some processing data
        GlobalRecordCount = Value('i', lock=True) # Will store count
        GlobalPercentageComplete = Value('i', lock=True)
        GlobalTiming = Value('f', lock=True)
        TooShortToTime = Value('i', lock=True)

        # Some of these values need to be set
        try:
            if GlobalTiming.acquire(True, 1000):
                GlobalTiming.value = time.time()
            if GlobalPercentageComplete.acquire(True, 1000):
                GlobalPercentageComplete.value = 0
            if TooShortToTime.acquire(True, 1000):
                TooShortToTime.value = 0
        except:
            pass
        finally:
            GlobalTiming.release()
            GlobalPercentageComplete.release()
            TooShortToTime.release()


        # TODO: Create a single dedicated process to handle web submissions and reporting
        # Form the queue!
        support_queue = Queue()

        supportproc = Process(
            target=elastic.core_posting_worker,
            args=(
                    support_queue,
                    GlobalRecordCount,
                    GlobalPercentageComplete,
                    GlobalTiming,
                    TooShortToTime
            ),
            name="support"
        )
        supportproc.start()

        # Start the processes for parsing event data
        for process in range(args.cores):
            proc_name = str(process)
            proc = Process(
                            target=parserecord,
                            args=(
                                    Tasks[process],
                                    file_path,
                                    total_records,
                                    int(args.buffer),
                                    args.index,
                                    nodes,
                                    GlobalRecordCount,
                                    GlobalPercentageComplete,
                                    GlobalTiming,
                                    TooShortToTime,
                                    args.debug,
                                    support_queue,
                                    args.token                 
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

        i = i + 1
        end_time = datetime.now()
        duration = end_time - start_time
        print("")
        print("File " + str(i) + " completed in: " + str(duration))   
        print("")





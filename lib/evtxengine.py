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

def parserecord(filename, num_items, logBufferSize, index, nodes, debug, support_queue, token=""):

    count = 0
    JSONevents = ""
    logBufferLength = 0
    count_postedrecord = 0
      
    parser = PyEvtxParser(filename)
    for record in parser.records_json():

            count = count + 1
            logBufferLength = logBufferLength + 1

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
                dump_batch(JSONevents, index, nodes, count_postedrecord, num_items, debug, support_queue, token)
                JSONevents = ""
                logBufferLength = 0

    if logBufferLength > 0:
        count_postedrecord = count_postedrecord + logBufferLength
        dump_batch(JSONevents, index, nodes, count_postedrecord, num_items, debug, support_queue, token)
        logBufferLength = 0
        JSONevents = ""

    return count_postedrecord
            

def dump_batch(events, index, nodes, count_postedrecord, num_items, debug, support_queue, token=""):
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
        
    # Report process in seperate thread. Main process should continue even if there are issues.
    support_queue.put({
                    "type":"report",
                    "data": {
                        "count_postedrecord": count_postedrecord,
                        "num_items": num_items
                    }
    })
    

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

def process_project(queue, support_queue, supportproc, process_queue, args):
    
    nodes = args.nodes.replace(" ", "").split(',')
    i = 0

    while True:
        try:
            file_path = process_queue.get(True, 1) # Try for up to 1 sec to get data, else give up
        
        except queues.Empty:
            break

        start_time = datetime.now()
        print("[" + str(datetime.now().replace(microsecond=0)) + "] -- [PROCESSING] " + file_path)
        
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

        if total_records == 0 or last == 0:
            print("[" + str(datetime.now().replace(microsecond=0)) + "] -- [INFO] No logs identified  in file " + file_path + ", skipping...")
            i = i + 1
            continue

        if total_records > 0:
            print("[" + str(datetime.now().replace(microsecond=0)) + "] -- [INFO] Counted " + str(total_records) + " logs in file " + file_path)

        records_in = parserecord(    file_path,
                        total_records,
                        int(args.buffer),
                        args.index,
                        nodes,
                        args.debug,
                        support_queue,
                        args.token                 
                    ) 

        i = i + 1
        end_time = datetime.now()
        duration = end_time - start_time
        print("[" + str(datetime.now().replace(microsecond=0)) + "] -- [COMPLETED] " + file_path + " in: " + str(duration) + " and counted " + str(records_in) + " records")   





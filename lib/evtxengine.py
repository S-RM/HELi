#!/usr/bin/env python

import requests, json, argparse, os, sys, re
from multiprocessing import Process, current_process, cpu_count, Manager, Value, Queue, queues
import threading
import mmap
import base64
import time
import Evtx.Evtx as evtx, xml.etree.ElementTree as ET
from datetime import datetime
import elastic
import projectengine

def chunk_and_count_evtx(log, cores, file_path):

    # First, we divvy up Chunks to multiple cores so that we can 
    # optimise creation of an index file of records, which will 
    # allow us to assign equal numbers of records to each core.

    # The first step, is to create an array of Chunks in the log
    chunks = iter(log.chunks())
    chunk_array = []
    chunk_size = 0
    try:
        while True:
            chunk = next(chunks)
            chunk_array.append(chunk._offset)
            chunk_size = chunk_size + 1
    except StopIteration:
        pass
 
    # Form the queue!
    primary_queue = Queue()
    # We have an array of chunks, now we can submit these to a queue
    for chunk in chunk_array:
        primary_queue.put(chunk)

    # We also use a queue to recieve data
    receive_queue = Queue()

    # Array to store processes
    procs = []
    # We know how many processes we want to spawn
    for task in range(0, int(cores)):
        proc = Process(target=count_records_in_batch, args=(primary_queue,file_path,receive_queue), name=str(task))
        procs.append(proc)
        proc.start()

    Index = {}
    Index['chunks'] = {}
    shutdown = False
    stop_counter = []

    while not shutdown:
        try:
            item = receive_queue.get() # We need to wait for at least something in the queue
            
            if item == "STOP":
                stop_counter.append("STOP")
                if len(stop_counter) >= cores:
                    raise queues.Empty() # This will be the last one
            else:
                Index['chunks'].update(item)

        except queues.Empty:
            shutdown = True
            break

    # Queue is empty, we can join the processes
    for proc in procs:
        proc.join()

    # TODO: Terminate any remaining processes       

    record_count = 0
    for chunk in Index['chunks']:
        record_count = record_count + Index['chunks'][chunk]['count']
    Index['total_records'] = record_count

    if record_count < 1:
        return False
    else:
        return Index['total_records']

def count_records_in_batch(queue, file_path, receive_queue):

    shutdown = False
    count = 0
    while not shutdown:

        count = count + 1
        
        # Check for up to one second if we can grab some data, else exit
        try:
            if not queue.empty():
                chunk_offset = queue.get(False)
            else:
                receive_queue.put("STOP")
                shutdown = True
                break
            

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

    with evtx.Evtx(filename) as log:
        records = iter(log.records())
        
        try:
            
            while True:

                record = next(records)
                
                if count >= start and count < end:

                    count = count + 1
                    # Then, proceed, we are in the sweet spot
                    events = {"System": {}, "EventData": {}}
                    root = ET.fromstring(record.xml())

                    for system_items in root[0]:
                        tag = re.search("(?<=}).*", system_items.tag).group(0)
                        events["System"][tag] = {}
                        
                        element_count = 0
                        for key, value in system_items.attrib.iteritems():
                            if key == "SystemTime":
                                if "." not in str(value):
                                    date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                                else:
                                    date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
                                date = str(date.isoformat())
                                events["System"][tag][key] = date
                            else:
                                events["System"][tag][key] = value

                            element_count = element_count + 1
                        
                        if system_items.text is not None:
                            if element_count == 0:
                                events["System"][tag] = system_items.text
                            else:
                                events["System"][tag]["Value"] = system_items.text

                    element_count = 0
                    for data_items in root[1]:
                        newData = {}
                        tag = re.search("(?<=}).*", data_items.tag).group(0)
                        unique_tag = tag + "__" + str(element_count)
                        newData[unique_tag] = {}

                        for key, value in data_items.attrib.iteritems():
                            newData[unique_tag][key] = value

                        newData[unique_tag]["Value"] = data_items.text
                        events["EventData"].update(newData)
                        element_count = element_count + 1

                    event_data = {}

                    for tag in events["EventData"]:
                        # reconstruct tag
                        real_tag = tag.split("__")[0]
                        event_data[real_tag] = {}

                    for tag in events["EventData"]:
                        # reconstruct tag
                        real_tag = tag.split("__")[0]
        

                        if len(events["EventData"][tag]) == 2 and "Name" in events["EventData"][tag] and "Value" in events["EventData"][tag] and events["EventData"][tag]["Value"]:
                            event_data[real_tag][events["EventData"][tag]["Name"]] = events["EventData"][tag]["Value"]

                        # This section is for when event logs are really unhelpful and just say <data>{value}</data>
                        # without indicating what the field means (despite a field name showing up in the Windoes Event Viewer).
                        # Basically, we can look these fields up manually, but for the meantime we need to add to some sort of dictionary
                        # to facilitate querying.

                        # TODO: We should add a database, maybe defined through a YAML file, that maps unknown event logs against known examples.
                        # Would have to be done manually, but could be added to over time. Potentially useful to update when the occassion calls
                        # for better insight into specific event ids.
                        elif len(events["EventData"][tag]) == 1 and "Value" in events["EventData"][tag]:

                            if real_tag == "Binary":
                                event_data[real_tag] = events["EventData"][tag]["Value"]

                            else:
                                tmp = events["EventData"][tag]["Value"]

                                if not tmp:
                                    continue

                                tmp = tmp.encode('utf-8')
                                split_tmp = str(tmp).split("<string>")

                                event_data[real_tag]['Strings'] = {}

                                if len(split_tmp) > 2:
                                    i = 0
                                    for string in split_tmp:
                                        string = string.strip().replace("</string>", "")
                                        if string and string != "\n":
                                            event_data[real_tag]['Strings'][i] = string.replace("</string>", "")
                                            i = i + 1

                                else:
                                    event_data[real_tag]['Strings'][0] = tmp.replace("</string>", "").replace("<string>", "")

    
                    events["EventData"] = event_data

                    JSONevents = JSONevents + '{"index": {}}\n'
                    JSONevents = JSONevents + json.dumps(events) + "\n" 

                    logBufferLength = logBufferLength + 1
                    
                    # Dump log buffer when full
                    if logBufferLength >= int(logBufferSize):
                        count_postedrecord = count_postedrecord + logBufferSize
                        dump_batch(JSONevents, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, support_queue, token)
                        JSONevents = ""
                        logBufferLength = 0


                elif count >= end:
                    # If we're bigger or equal to end, break
                    break

                else:
                    count = count + 1

        except StopIteration:
            if logBufferLength > 0:
                count_postedrecord = count_postedrecord + logBufferLength
                dump_batch(JSONevents, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, support_queue, token)
                logBufferLength = 0
                JSONevents = ""


        finally:
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
        MadeItThrough = True
        with open(file_path, "rb") as file:
            buffer = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            header = evtx.FileHeader(buffer, 0x0) #All evtx files will have to have a header
            if header.verify():
                if header.first_chunk().first_record()._offset >= buffer.size():
                    bad_files[bad_files_count] = {}
                    bad_files[bad_files_count]['path'] = file_path
                    bad_files[bad_files_count]['reason'] = "File is too small to contain valid records."
                    bad_files_count = bad_files_count + 1
                    MadeItThrough = False
            else:
                bad_files[bad_files_count] = {}
                bad_files[bad_files_count]['path'] = file_path
                bad_files[bad_files_count]['reason'] = "Failed EVTX header verification."
                bad_files_count = bad_files_count + 1
                MadeItThrough = False
        except Exception as e:
            bad_files[bad_files_count] = {}
            bad_files[bad_files_count]['path'] = file_path
            bad_files[bad_files_count]['reason'] = e.message + ": File may be corrupt, or there's something wrong with my code."
            bad_files_count = bad_files_count + 1
            MadeItThrough = False
        
        if MadeItThrough == True:
            new_file_list.append(file_path)

        del buffer

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
        print ""
        print "### File " + str(i + 1) + " of " + str(queue['count']) + ": " + file_path
        start_time = datetime.now()
        print "### " + str(start_time)
        print ""
        
        # First, lets instantiate the EVTX object
        evtxObject = evtx.Evtx(file_path)
        with evtxObject as log:
            RecordCount = chunk_and_count_evtx(log, args.cores, file_path)
            if RecordCount is False:
                print "No logs in file, skipping..."
                i = i + 1
                continue
        
        # We need to calculate how many records to assign to each process
        record_batch = (RecordCount / args.cores)
        remainder = RecordCount - (record_batch * args.cores)
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

        print "There are " + str(RecordCount) + " logs in total."
        print "Allocating " + str(record_batch) + " logs per process with " + str(store_remainder) + " remainder."


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
                                    RecordCount,
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
        print ""
        print "File " + str(i) + " completed in: " + str(duration)      
        print ""      





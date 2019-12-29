#!/usr/bin/env python

# import required libraries
import requests, json, argparse, xmltodict, os, sys
from multiprocessing import Process, current_process, cpu_count, Manager, Pipe, Value, Queue, queues
import threading
from collections import OrderedDict
from datetime import datetime
import Evtx.Evtx as evtx
from Evtx.Views import evtx_record_xml_view
import mmap
import base64
import time


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
        log_file = open(file_path, 'rb')
        buffer = mmap.mmap(log_file.fileno(), 0, access=mmap.ACCESS_READ)

        Chunk = evtx.ChunkHeader(buffer, chunk_offset)
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
        

def parserecord(task, filename, num_items, logBufferSize, index, nodes, GlobalRecordCount, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, token=""):

    start = task['start']
    batch = task['count']
    end = (start + batch)
    count = 0

    events = ""
    logBufferLength = 0
    count_postedrecord = 0

    with evtx.Evtx(filename) as log:
        records = iter(log.records())
        
        try:
            
            while True:
                if count >= start and count < end:
                    
                    # Then, proceed, we are in the sweet spot
                    count = count + 1
                    record = next(records)
                    xml = evtx_record_xml_view(record)
                    log_line = xmltodict.parse(xml)

                    # Format the date field
                    date = log_line.get("Event").get("System").get("TimeCreated").get("@SystemTime")
                    if "." not in str(date):
                        date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
                    else:
                        date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S.%f")
                    log_line['@timestamp'] = str(date.isoformat())
                    log_line["Event"]["System"]["TimeCreated"]["@SystemTime"] = str(date.isoformat())

                    # Process the data field to be searchable
                    data = ""
                    if log_line.get("Event") is not None:
                            data = log_line.get("Event")
                            if log_line.get("Event").get("EventData") is not None:
                                data = log_line.get("Event").get("EventData")
                                if log_line.get("Event").get("EventData").get("Data") is not None:
                                    data = log_line.get("Event").get("EventData").get("Data")
                                    if isinstance(data, list):
                                        data_vals = {}
                                        for dataitem in data:
                                            try:
                                                if dataitem.get("@Name") is not None:
                                                    data_vals[str(dataitem.get("@Name"))] = str(
                                                        str(dataitem.get("#text")))
                                            except:
                                                pass
                                        log_line["Event"]["EventData"]["Data"] = data_vals
                                    else:
                                        if isinstance(data, OrderedDict):
                                            log_line["Event"]["EventData"]["RawData"] = json.dumps(data)
                                        else:
                                            log_line["Event"]["EventData"]["RawData"] = data.encode('utf-8')
                                        del log_line["Event"]["EventData"]["Data"]
                                else:
                                    if isinstance(data, OrderedDict):
                                        log_line["Event"]["RawData"] = json.dumps(data)
                                    else:
                                        log_line["Event"]["RawData"] = str(data)
                                    del log_line["Event"]["EventData"]
                            else:
                                if isinstance(data, OrderedDict):
                                    log_line = dict(data)
                                else:
                                    log_line["RawData"] = str(data)
                                    del log_line["Event"]
                    else:
                        pass
                    events = events + '{"index": {}}\n'
                    events = events + json.dumps(log_line) + "\n"
                    logBufferLength = logBufferLength + 1


                    # Dump log buffer when full
                    if logBufferLength >= int(logBufferSize):
                        count_postedrecord = count_postedrecord + logBufferSize
                        dump_batch(events, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, token)
                        events = ""
                        logBufferLength = 0

                elif count >= end:
                    # If we're bigger or equal to end, break
                    break

                else:
                    # Otherwise, we're obviously not there yet
                    count = count + 1

        except StopIteration:
            if logBufferLength > 0:
                count_postedrecord = count_postedrecord + logBufferLength
                dump_batch(events, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, token)
                logBufferLength = 0

        finally:
            if logBufferLength > 0:
                count_postedrecord = count_postedrecord + logBufferLength
                dump_batch(events, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, token)
                logBufferLength = 0

def dump_batch(events, index, nodes, GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime, debug, token=""):
    if not debug:
        # Web requests always work better in a thread. Waiting for network latency is silly.
        post_thread = threading.Thread(target=postToElastic, args=(events, index, nodes,token))
        post_thread.start()

    # Report process in seperate thread. Main process should continue even if there are issues.
    report_thread = threading.Thread(target=report_progress, args=(GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime,))
    report_thread.start()

    report_thread.join()
    if not debug:
        post_thread.join()


def report_progress(GlobalRecordCount, logBufferLength, num_items, GlobalPercentageComplete, GlobalTiming, TooShortToTime):

    report = ""

    # If we can't acquire any of the variables, let's just quit this report.

    if GlobalRecordCount.acquire(True, 1000): # Try for 1000 ms to acquire
        # Now we can send the update
        GlobalRecordCount.value = GlobalRecordCount.value + logBufferLength        
        record_count = GlobalRecordCount.value
    else:
        return False

    if GlobalPercentageComplete.acquire(True, 1000):
        last_update = GlobalPercentageComplete.value
    else:
        return False

    if GlobalTiming.acquire(True, 1000):
        processing_time = GlobalTiming.value
    else:
        return False

    if TooShortToTime.acquire(True, 1000):
        TooShort = TooShortToTime.value
    else:
        return False

    # If anything at all goes wrong, let's just make sure the lock is released
    try:
        # Calculate the percentage
        percentage_float = (float(record_count) / float(num_items)) * 100
        percentage = int(percentage_float)

        # Percentage updates change frequency depending on how long we expect processing to last
        if ((percentage > last_update) and (percentage <= last_update + 10) and (percentage_float > 5) and (num_items < 2000000)) or ((percentage > last_update) and (percentage <= last_update + 10) and (percentage_float > 1) and num_items >= 2000000) or (percentage >= 100): # greater than 3% to give us better data
            # Output update about the proccessing
            report = "Processing file: " + str(record_count) + " / " + str(num_items) + " (" + str(percentage) + "%)"
            GlobalPercentageComplete.value = last_update + 10

            # We can also do something clever and try to calculate an ETA for completion
            # Calculate time delta
            update_time = time.time()
            delta = update_time - processing_time
            left_to_complete = 100 / percentage_float
            eta = (delta * left_to_complete) - (delta)
            
            if (TooShort == 0) or (TooShort == 1 and eta > 120):

                if eta > 120 and num_items > 10000: # If we have less than 10,000, not worth it

                    if eta >= 60 and eta < 3600:
                        report = report + " -- Estimated time remaining: " + str(int(eta / 60)) + " minutes"
                    
                    elif eta >= 3600:
                        report = report + " -- Estimated time remaining: " + str(round(eta / 3600, 2)) + " hours"

                    else:
                        report = report + " -- Estimated time remaining: " + str(int(eta)) + " seconds"

                else:
                    report = report + " -- Estimated time remaining:" + " a few minutes"
                    TooShortToTime.value = 1

    except Exception as e:
        print "Error in reporting: " + str(e)

    finally:
        # In case anything goes wrong
        # And now release the variable
        if len(report) > 0:
            print report
        GlobalRecordCount.release()
        GlobalPercentageComplete.release()
        GlobalTiming.release()
        TooShortToTime.release()

def postToElastic(events, index, nodes, token=""):

    # Start the node fault-tolerance
    currentNode = 0

    # Continuously attempt to post to nodes; when one fails, try the next if listed
    success = False
    results = {}
    count = 0
    headers = {}
    headers['content-type'] = "application/x-ndjson"
    if token != "":
        headers['Authorization'] = "Basic " + token
    while not success:
        try:
            # Post to current node
            results = requests.post("http://" + nodes[currentNode] + "/" + index + "/doc/_bulk", data=events, headers=headers)
            if results.status_code == 200:
                success = True

            elif results.status_code == 429:
                if count < len(nodes):
                    currentNode = (currentNode + 1) % len(nodes)
                    count = count + 1
                    pass
                else:
                    print json.dumps(results.json(), indent=4)
                    break
            else:
               print json.dumps(results.json(), indent=4)
               break

        except Exception as e:
            # Move to the next node; loop back if tried all available
            if len(nodes) > 1:
                currentNode = (currentNode + 1) % len(nodes)
            print str(e)


    if not results.ok:
        print json.dumps(results.json(), indent=4)

    else:
        pass

def validate_log_files(file_list):

    # For a log file to be valid, it needs to have at least one
    # record, otherwise there's no point in processing it!

    bad_files = {}
    bad_files_count = 0
    new_file_list = []

    #Check to see if the evtx file is big enough to store data
    for file_path in file_list:
        MadeItThrough = True
        file = open(file_path, "rb")
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
            bad_files[bad_files_count]['reason'] = e + ": File may be corrupt, or there's something wrong with my code."
            bad_files_count = bad_files_count + 1
            MadeItThrough = False
        
        if MadeItThrough == True:
            new_file_list.append(file_path)

    return_data = {}
    return_data['count'] = len(new_file_list)
    return_data['files_to_process'] = []
    return_data['files_to_process'] = new_file_list
    return_data['errors'] = {}
    return_data['errors'] = bad_files

    return return_data

def prepare_files_to_process(path, folder_priorities=[], log_priorities=[], strict_mode=False):

    file_list = {}
    file_list['count'] = 0
    file_list['order'] = []

    path = os.path.abspath(path) 

    if len(folder_priorities) > 0:
        for folder in folder_priorities:
            # Construct path
            temp_path = os.path.join(path, folder)
            if len(log_priorities) > 0:
                for log in log_priorities:
                    log_path = os.path.join(temp_path, log)
                    if os.path.exists(log_path):
                        file_list['order'].append(log_path)

            # For each folder, get list of files
            else:
                # We want all files within these folders
                for temp_path, subdirs, names in os.walk(temp_path):
                    for name in names:
                        file_list['order'].append(os.path.join(temp_path, name))

        # We now need to add all log priorities across all other folders not specificed, 
        # as these logs still need to be prioritised
        if len(log_priorities) > 0 and not strict_mode:
            for log in log_priorities:
                for temp_path, subdirs, names in os.walk(path):
                    for subdir in subdirs:
                            if os.path.exists(os.path.join(temp_path, subdir, log)) and os.path.join(temp_path, subdir, log) not in file_list['order']:
                                file_list['order'].append(os.path.join(temp_path, subdir, log))

        # FINALLY, we need to ensure that any remainding files within our prioritised folders are appended, before the rest of the stuff is.
        # Only if strict_mode is on though, as otherwise we would only stick to the prioritised logs within each folder.
        if not strict_mode:
            for folder in folder_priorities:
                # Construct path
                temp_path = os.path.join(os.path.abspath(path), folder)
                for temp_path, subdirs, names in os.walk(temp_path):
                    for name in names:
                        if os.path.exists(os.path.join(temp_path, name)) and os.path.join(temp_path, name) not in file_list['order']:
                            file_list['order'].append(os.path.join(temp_path, name))

    elif len(log_priorities) > 0:
        for log in log_priorities:
            for temp_path, subdirs, names in os.walk(path):
                for subdir in subdirs:
                        if os.path.exists(os.path.join(temp_path, subdir, log)) and os.path.join(temp_path, subdir, log) not in file_list['order']:
                            file_list['order'].append(os.path.join(temp_path, subdir, log))

    if strict_mode:
        # We do nothing, as we've already got out list
        pass
    # Only remaining possability is that either logs and folders are not defined, or we need to add all the rest to this list.
    # Either way, this logic encompasses both possabilities.
    else:
        # We add the remaining items to the list, ignoring paths we already have. 
        # This list will be structured in the way os.walk() sorts the files, and will
        # not follow on from any folder priorities, etc.
        for path, subdirs, names in os.walk(path):
            for name in names:
                if not os.path.join(path, name) in file_list['order']:
                    if name.endswith('.evtx'):
                        file_list['order'].append(os.path.join(path, name))

    # Awesome, we finally have a tasty list of nicely organised files,
    # but now we need to check if these files are actually valid, real,
    # and contain at least one log.
    queue = validate_log_files(file_list['order'])
    
    # Now let's hand the deets back to the main function
    return queue

def initiate_project(args):
    
    folder_priorities = args.pfolder.split(',')
    folder_priorities = [folder.strip() for folder in folder_priorities]
    folder_priorities = filter(None, folder_priorities)

    log_priorities = args.plog.split(',')
    log_priorities = [log.replace('.evtx', '').strip() for log in log_priorities]
    log_priorities = filter(None, log_priorities)
    log_priorities = [log + '.evtx' for log in log_priorities]

    print ""
    print ""
    print "----------------------------------------------------------"
    print "----------------------------------------------------------"
    print ""
    print "###########################"
    print "#   General Information   #"
    print "###########################"
    print "Number of Cores: " + str(args.cores)
    print "Buffer Size: " + str(args.buffer)
    print "Index Name: " + str(args.index)
    print "Nodes: " + str(args.nodes)
    if args.debug:
        print "Debug Mode: True"
    print ""
    print "###########################"
    print "#   Project Information   #"
    print "###########################"

    if args.file:
        print "File Selected: " + str(os.path.abspath(args.file))
        queue = validate_log_files([os.path.abspath(args.file)])

    elif args.directory:
        print "Folder Selected: " + str(os.path.abspath(args.directory))

        queue = prepare_files_to_process(args.directory, folder_priorities, log_priorities, args.strict)
        if queue['count'] <= 0:
            print "There are no log files within this directory that we could find."
            exit()

        print "Total number of files: " + str(queue['count'])
     
        if args.strict:
            print "Strict Mode: True"
        else:
            print "Strict Mode: False" 

        if args.plog != "":
            print "Prioritising these logs(s):"
            for log in log_priorities:
                print "    - " + log

        if args.pfolder != "":
            print "Prioritising these folder(s):"
            for folder in folder_priorities:
                print "    - " + folder.upper()

        if args.debug:
            print "List of files in order of processing:"
            for name in queue['files_to_process']:
                print "    - " + name

        if len(queue['errors']) > 0:
            print ""
            print "WARNING: We identified errors in " + str(len(queue['errors'])) + " EVTX file(s). This is often because log files are empty or corrupted."
            if args.debug:
                print "         If you continue, these files will be ignored. See below for detailed information."
                print ""
                print "Detailed Errors:"
                print ""
                for error in queue['errors']:
                    print str(error) + " -    " + "Path: " + queue['errors'][error]['path']
                    print "       Reason: " + queue['errors'][error]['reason']
            else:
                print "         If you continue, these files will be ignored. Run this script in debug mode to see further details."

    print ""
    print "----------------------------------------------------------"
    print "----------------------------------------------------------"
    print ""
    print ""

    return queue

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

        # If record_batch is not zero, there is at least one record per task
        if record_batch > 0:
            Tasks = {}
            start = 0
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

        # We should have already caught and removed log files with < 1 logs in total
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
        print "Allocating an average of " + str(record_batch) + " logs per process."

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

        for process in range(args.cores):
            proc_name = str(process)
            proc = Process(target=parserecord, args=(Tasks[process],file_path,RecordCount,int(args.buffer),args.index,nodes,GlobalRecordCount,GlobalPercentageComplete,GlobalTiming,TooShortToTime,args.debug, args.token), name=proc_name)
            procs.append(proc)
            proc.start()

        # Complete the processes
        for proc in procs:
            proc.join()

        i = i + 1
        end_time = datetime.now()
        duration = end_time - start_time
        print ""
        print "File " + str(i) + " completed in: " + str(duration)      
        print ""      


if __name__ == "__main__":

    # Create argument parser
    parser = argparse.ArgumentParser()
    
    # Add arguments
    # Specify File or Folder, but not both
    fileorfolder = parser.add_mutually_exclusive_group(required=True)
    fileorfolder.add_argument("--file", "-f", default=False, help="Enter the evtx file: --file security.evtx or -f security.evtx")
    fileorfolder.add_argument("--directory", "-d", default=False, help="Enter the directory where the evtx files are stored. This can include multi-level directories. Use the full file path. ")
     
    # Optional arguments
    parser.add_argument("--cores", "-c", default=cpu_count(),type=int,help="Enter the number of processes to run: --cores 8 or -c 8.  This defaults to your total core count")
    parser.add_argument("--buffer", "-b", default= 1000,help="Enter the number of records to store in buffer before sending to elasticsearch: --buffer 1000 or -b 1000.  This defaults to 1000")
    parser.add_argument("--index", "-i", default='projectx',help="Enter the index name for elasticsearch: --index projectx or -i projectx. This defaults to projectx")
    parser.add_argument("--nodes", "-n", default='127.0.0.1:9200',help="Enter the IP Address and Port for elasticsearch: --nodes 127.0.0.1:9200 or -n 127.0.0.1:9200. This can include multiple nodes using a comma ',' to seperate the nodes and wrapped in quotes e.g. '192.168.1.2:9200,192.168.1.3:9200'. This defaults to 127.0.0.1:9200")
    parser.add_argument("--token", "-a", default='', help="Enter credentials in the format: USERNAME:PASSWORD")
    
    # Requires folder argument
    parser.add_argument("--pfolder", "-p", default='', help="For multi-file processing, if your files are organised in the format identifier/evtx_file, then you can list the folders that this script should process first in the format of identifier, identifier.")
    parser.add_argument("--plog", "-l", default='', help="For multi-file processing, you can specify the names of logs you would like to process first across all files, e.g., \"security, application, system\". These names are case-insensitive with or without the .evtx extension. Files you specifiy will be processed first before other files are consiered. When combined with folder prioritisation, these files will be processed first within each folder.")
    parser.add_argument("--strict", "-s", action='store_true', help="When this flag is set, only the folders and logs specified as priorities will be processed whilst in directory mode.")    
    
    parser.add_argument("--debug", default=False, action='store_true', help="In debug mode, events are not submitted to an index and more verbose performance information is displayed.")
    
    args = parser.parse_args()

    # Encode token if listed
    if args.token != "":
        args.token = args.token.strip()
        args.token = base64.b64encode(args.token)

    # Check we're dealing with valid paths before continuing
    if args.file and not os.path.exists(args.file):
       print "The file or folder path you specified does not exist."
       print args.file
       exit()

    if args.directory and not os.path.exists(args.directory):
       print "The file or folder path you specified does not exist."
       exit()

    # TODO: We need to verify that log and folder prioritisation actually contains at least one item
    # TODO: Strict mode cannot be enabled unless log or folder priorities are specified
    # TODO: Add in validator function


    procs = []

    # Display project banner, list configurations, and receive queue
    project = initiate_project(args)
    start_datetime = datetime.now()

    raw_input("Project initiated, press Enter to begin processing...")

    print ""
    print "### Project Starting ###"
    print ""
    process_project(project, args)
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




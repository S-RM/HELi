
import argparse, base64, os, time
from multiprocessing import cpu_count
import evtxengine



# Create argument parser
parser = argparse.ArgumentParser()

######
### Mandatory arguments
######

# Specify File or Folder mode, but not both
fileorfolder = parser.add_mutually_exclusive_group(required=True)

fileorfolder.add_argument(
    "--file",
    "-f",
    default=False,
    help=
    """
    Enter the evtx file: --file security.evtx or -f security.evtx
    """
)

fileorfolder.add_argument(
    "--directory",
    "-d",
    default=False,
    help=
    """
    Enter the directory where the evtx files are stored. This can \
    include multi-level directories. Use the full file path.
    """
)


######
### Optional arguments
######

parser.add_argument(
    "--cores",
    "-c",
    default=cpu_count(),
    type=int,
    help=
    """
    Enter the number of processes to run, e.g., --cores 8 or -c 8. \
    This defaults to your total core count
    """
)
parser.add_argument(
    "--buffer",
    "-b",
    default=1000,
    type=int,
    help=
    """
    Enter the number of records to store in buffer before sending to \
    elasticsearch: --buffer 1000 or -b 1000.  This defaults to 1000.
    """
)

parser.add_argument(
    "--index",
    "-i",
    default='projectx',
    help=
    """
    Enter the index name for elasticsearch: --index projectx or -i \
    projectx. This defaults to projectx.
    """
)

parser.add_argument(
    "--nodes",
    "-n",
    default='127.0.0.1:9200',
    help=
    """
    Enter the IP Address and Port for elasticsearch: --nodes \
    127.0.0.1:9200 or -n 127.0.0.1:9200. This can include multiple \
    nodes using a comma ',' to seperate the nodes and wrapped in \
    quotes e.g. '192.168.1.2:9200,192.168.1.3:9200'. This defaults \
    to 127.0.0.1:9200.
    """
)

parser.add_argument(
    "--token",
    "-t",
    default='',
    help=
    """
    Enter credentials in the format: USERNAME:PASSWORD
    """
)

# Requires folder argument
parser.add_argument(
    "--pfolder",
    "-p",
    default='empty',
    help=
    """
    For multi-file processing, if your files are organised in the format \
    identifier/evtx_file, then you can list the folders that this script \
    should process first in the format of identifier, identifier.
    """
)

parser.add_argument(
    "--plog",
    "-l",
    default='empty',
    help=
    """
    For multi-file processing, you can specify the names of logs you \
    would like to process first across all files, e.g., \"security, \
    application, system\". These names are case-insensitive with or \
    without the .evtx extension. Files you specifiy will be processed \
    first before other files are consiered. When combined with folder \
    prioritisation, these files will be processed first within \
    each folder.
    """
)
parser.add_argument(
    "--strict",
    "-s",
    action='store_true',
    help=
    """
    When this flag is set, only the folders and logs specified as \
    priorities will be processed whilst in directory mode.
    """
)    

parser.add_argument(
    "--debug",
    default=False,
    action='store_true',
    help=
    """
    In debug mode, events are not submitted to an index and more \
    verbose performance information is displayed.
    """
)

args = parser.parse_args()

######
### Argument validation
######

# Encode token if listed
if args.token != "":
    # TODO: Check it is in right format
    args.token = args.token.strip()
    args.token = base64.b64encode(args.token)

# Check we're dealing with a valid file path before continuing
if args.file and not os.path.exists(args.file):
    print "The file path you specified does not exist."
    print args.file
    exit()

# Check we're dealing with a valid folder path before continuing
if args.directory and not os.path.exists(args.directory):
    print "The folder path you specified does not exist."
    print args.directory
    # TODO: Check there is at least one file here
    exit()

if args.strict:
    if not args.plog and not args.pfolder:
        print "You cannot enable --strict mode unless --plog and/or --pfolder are specified."
        exit()

if args.plog is not "empty":
    if args.file:
        print "--plog cannt be set in file mode."
        exit()

if args.pfolder is not "empty":
    if args.file:
        "--pfolder cannt be set in file mode."
        exit()    


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
    queue = evtxengine.validate_log_files(file_list['order'])
    
    # Now let's hand the deets back to the main function
    return queue



def initiate():
    
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
        queue = evtxengine.validate_log_files([os.path.abspath(args.file)])

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

    # We minus one core, since we dedicate one solely for support functions
    args.cores = args.cores - 1

    return {"queue" : queue, "args" : args}


import argparse, base64, os
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

        queue = evtxengine.prepare_files_to_process(args.directory, folder_priorities, log_priorities, args.strict)
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

    return {"queue" : queue, "args" : args}

# HELi - Helpful Event Log Ingestor

HELi (pronounced *hee*-*lee*) is a Windows Event Log parser written in Python. We have designed it to help incident responders rapidly ingest Windows Event Logs from EVTX files into an Elasticsearch index.

#### Who is this for?

HELi solves a specific problem that incident responders face when investigating incidents within Windows-based IT environments lacking a SIEM. 

In these cases, the responder must quickly collect and analyse Windows Event Logs, sometimes in very large quantities. However, once collected, they are restricted in how they can view this information. The Windows Event Viewer is notoriously difficult to work with and PowerShell commands (which utilise the same backend engine) are just as slow. 

Elasticsearch offers one of the best ways to search and interpret this information; however, existing tools designed to ingest EVTX files, such as [Winlogbeat](https://www.elastic.co/products/beats/winlogbeat) or [evtxtoelk](https://github.com/dgunter/evtxtoelk), are generally designed to work in coordination with a SIEM or lack the speed required in an incident response scenario.

HELi addresses this problem by allowing the responder to utilise multiple cores to ingest EVTX files into an Elasticsearch index, thereby providing an accessible means of investigating Windows Events in a fraction of the time provided by other tools.

## Features

Designed specifically to give incident responders visibility into vast amounts of EVTX data, the main features of HELi are:

- Fully multicore processing (tested up to 128 cores).
- Parses Event Log XML into properly nested JSON.
- Memory efficient; generally less than 40mb RAM required per core .
- Supports production Elasticsearch environments with multiple nodes.
- Recursive discovery of EVTX files within directories.
- Can prioritise ingesting specific types of Event Logs, such as Security or System logs.
- Validation of Event Logs submitted to Elasticsearch (i.e., checks that records in = records out).
- Estimated processing times for each EVTX file.

## Requirements

For now, we only officially support HELi on Python2. It requires the following modules:

- requests
- xmltodict
- python-evtx

## Acknowledgements

HELi would not exist without the brilliant work by [@williballenthin](https://github.com/williballenthin) with the [python-evtx](https://github.com/williballenthin/python-evtx) module, which saved us from the considerable pain of having to develop our own parser for the EVTX file format.

All credit to development goes to [@MDR-DannyR](https://github.com/MDR-DannyR) and [@Sankgreall](https://github.com/Sankgreall).

# Usage

You can use HELi in three different modes, each of which applies itself to a different incident response scenario. In short, these use cases are:

- **Individual File Mode.** Send the logs from a single EVTX file into an Elasticsearch index.
- **Directory Mode.** Recursively discover all EVTX files within a given directory and send the logs from all files into an Elasticsearch index.
- **Directory Mode with Prioritisations**. Recursively discover all EVTX files within a directory, but provide additional parameters to prioritise certain types of logs or subfolders. This mode ensures a responder is able to specify the most critical information to ingest first.

The sections below outline these modes in further detail.

## Individual File Mode

At its simplest, you can use HELi to parse individual EVTX files and transmit the Event Log data into an Elasticsearch index, using as many cores as you can provide.

By default, HELi will send processed logs over the Elasticsearch bulk upload API to `127.0.0.1:9200` under the index name `projectx`. Refer to the Parameters section for further configuration information.

## Directory Mode

Directory Mode is functionally similar to Individual File Mode, with the exception that you can specify a folder rather than a single file. HELi will then recursively search that folder for all EVTX files and process them one at a time in the same manner as with Individual File Mode.

This mode is most useful when you have a large quantity of Event Logs to ingest in one go. 

## Directory Mode with Prioritisations

Although Directory Mode is useful, it has limitations when dealing with larger projects. For example, we commonly collect thousands of Event Logs from IT environments and organise them in a file structure like below:

- Hostname
  - Event Log
  - Event Log
  - ...

Even in the early stage of an incident response, we often suspect that certain machines (such as the domain controllers) or specific types of Event Logs (such as Security.evtx) will be critical for our analysis. Waiting for HELi to process these artefacts in Directory Mode could take a long time and our hinder our ability to provide timely information.

To address this problem, we can instruct HELi to prioritise artefacts using a combination of the following parameters:

- Subfolder; and,
- Event Log name.

For example:

```
./HELi.py -d ./logs -p AD-01,AD-02 -l Security.evtx,Application.evtx,System.evtx
```

Executing HELi with the above configuration would ingest Event Logs in the following order:

- Folder: AD-01
  - Event Log: Security.evtx
  - Event Log: Application.evtx
  - Event Log: System.evtx
- Folder: AD-02
  - Event Log: Security.evtx
  - Event Log: Application.evtx
  - Event Log: System.evtx
- *Revert to Directory Mode for remainder of project...*

Furthermore, sometimes a responder will collect Event Logs from an IT environment to ensure that data is preserved, but subsequently identify that their analysis needs to only focus on a few key machines.

Rather than have the responder copy and paste folders and logs in order to run HELi in Directory Mode without ingesting the remaining data, you can instruct HELi to prioritise artefacts in strict mode:

```
./HELi.py -d ./logs -p AD-01,AD-02 -l Security.evtx,Application.evtx,System.evtx --strict
```

The above example will work exactly as the previous example, except it will not process and Event Logs outside of the three logs you have specified within `AD-01` and `AD-02`.

## Parameters

The tables below list the required and optional parameters HELi supports, alongside a description of their functionality.

#### Required

| Parameter   | Short Parameter | Description                                                  |
| ----------- | --------------- | ------------------------------------------------------------ |
| --file      | -f              | Specify the EVTX file to process in Individual File Mode with a relative or absolute path. On Linux systems, this parameter is case-sensitive. |
| --directory | -d              | Specific the folder to process in Directory Mode or Directory Mode with Prioritisations with a relative or absolute path. On Linux systems, this parameter is case-sensitive. |

#### Optional

| Parameter | Short Parameter | Default Value         | Description                                                  |
| --------- | --------------- | --------------------- | ------------------------------------------------------------ |
| --cores   | -c              | \# of cores supported | You can specify the number of cores to use during processing. If left blank, this value will default to the number of cores supported by your machine, as detected by the Python`multiprocessing.cpu_count()` function. |
| --buffer  | -b              | 1,000                 | Event Logs are processed and submitted to Elasticsearch in batches equal to the value of this parameter. The implications of how this value affects overall processing time are not fully understood, therefore, we recommend using the default value for now. |
| --index   | -i              | projectx              | This parameter specifies the destination Elasticsearch index for ingesting Event Logs. Remember that Elasticsearch indexes have naming restrictions, and only support lowercase characters. Refer [here](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-create-index.html) for more information. |
| --nodes   | -n              | 127.0.0.1:9200        | You can specify multiple Elasticsearch nodes, which THELP will cycle through if the first node returns an HTTP error code (such as `HTTP 429`) when uploading Event Logs. Use comma separated values if specifying more than one node, for example, `"10.0.0.1:9200,10.0.0.2:9200,10.0.0.3:9200"`. If you don't specify a value, THELP will assume there is an Elasticsearch index available on localhost. |
| --token   | -t              | None                  | Elasticsearch supports Basic Authentication. If you secure your Elasticsearch with a username and password you can provide these here in the format `USERNAME:PASSWORD`. The default setting is not to use Basic Authentication. |
| --pfolder | -p              | None                  | When processing a directory with subfolders, you can choose to prioritise certain subfolders and ensure they are processed first.<br /><br />You can specify multiple subfolders using comma separated values, and the order you list them in will be enforced, for example, "dc-01, dc-02, dc-03" will process `dc-01` first before moving on to `dc-02`, and so on. If you don't specify a value, subfolders will be processed in alphabetical order.<br /><br />When combined with the --prioritiselog parameter, this behaviour changes slightly. Refer to *Directory Mode with Prioritisations*. |
| --plog    | -l              | None                  | When processing a directory, you can choose to prioritise certain logs and ensure they are processed before all other files.<br /><br />You can specify multiple file names using comma separated values, and the order you list them in will be enforced, for example, "Security.evtx,Application.evtx" will process `Security.evtx` files first (across all folders) before moving on to `Application.evtx`. If you don't specify a value, files will be processed in alphabetical order. |
| --strict  | -s              | False                 | Used in conjunction with `--prioritisefolder` or `--prioritiselogs`, this parameter will ensure that only the files or folders you specified will be processed. Refer to *Directory Mode with Prioritisations* for more information on this behaviour. |
| --debug   | None            | False                 | Enabling the `--debug` flag will disable posting any data to Elasticsearch and will provide a more verbose project description banner. If used with `--prioritisefolder` or `--prioritiselogs`, the order of the files to process will be listed. |

# Known Issues and Next Steps

In most situations, HELi functions as expected. However, even such a small application as this is beget by small issues and desired improvements. 

## Limitations

Reducing the processing time for Event Logs is a key objective of this project. Our efforts to improve HELi's overall speed has hit a bottleneck with parsing the Event Log XML data into a dictionary with the `xmltodict` library, which is a time-intensive operation.

We are investigating three design changes to increase the speed of this operation:

- **Moving HELi  to PyPi**, which initial testing has confirmed yields significant speed improvements. One key consideration here is that 64-bit PyPi is only supported on Linux systems, which means that a Windows-bound PyPi implementation of HELi could only support EVTX files that do not exceed 32-bit integers.
- **Develop our own Event Log XML parser in Python**, this would likely look like a stripped down XML parser that uses multiple XPath queries to construct a dictionary.
- **Develop our own Event Log XML parser in C++**. Parsing XML in C++ and calling the function from HELi would offer substantial speed improvements, most likely beyond that offered by PyPi.

## Issues to Fix

- [ ] For an as-yet-unknown reason, the HELi processes sometimes idle during a project. Sending a Keyboard Interrupt (CTRL+C) resumes the processes without causing data loss.

## Improvements

- [ ] Address speed improvements (refer to *Limitations*).
- [ ] Provider prettier and more useful logging, including as an external log file.
- [ ] Choose how to handle various HTTP errors from Elasticsearch; terminate or continue?
- [ ] Streamline uploading of Event Log data to Elasticsearch and investigate speed improvements.
- [ ] Create an explicit mapping for Elasticsearch documents.
- [ ] Generally clean the code and remove some inefficiencies!




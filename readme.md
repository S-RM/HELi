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
- Memory efficient; generally between 30-40mb RAM required per core.
- Supports production Elasticsearch environments with multiple nodes.
- Recursive discovery of EVTX files within directories.
- Can prioritise ingesting specific types of Event Logs, such as Security or System logs.
- Validation of Event Logs submitted to Elasticsearch (i.e., checks that records in = records out).
- Estimated processing times for each EVTX file.

## Requirements

For now, we only officially support HELi on Python2. It requires the following modules:

- requests
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

By default, HELi will send processed logs over the Elasticsearch bulk upload API to `127.0.0.1:9200` under the index name `projectx`. Refer to the *Parameters* section for further configuration information.

## Directory Mode

Directory Mode is functionally similar to Individual File Mode, with the exception that you can specify a folder rather than a single file. HELi will then recursively search that folder for all EVTX files and process them one at a time in the same manner as with Individual File Mode.

This mode is most useful when you have a large quantity of Event Logs to ingest in one go. 

## Directory Mode with Prioritisations

Although Directory Mode is useful, it has limitations when dealing with larger projects. For example, we commonly collect thousands of Event Logs from IT environments and organise them in a file structure such as indicated below:

- Hostname
  - Event Log
  - Event Log
  - ...
- Hostname
  - ...

Even in the early stage of an incident response, we often suspect that certain machines (such as the domain controllers) or specific types of Event Logs (such as Security.evtx) will be critical for our analysis. Waiting for HELi to process these artefacts in Directory Mode could take a long time and hinder our ability to provide timely information.

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
- Folder: AD-02
  - Event Log: Security.evtx
- Folder: AD-01
  - Event Log: Application.evtx
- Folder: AD-02
  - Event Log: Application.evtx
- Folder: AD-01
  - Event Log: System.evtx
- Folder: AD-02
  - Event Log: System.evtx
- *Revert to Directory Mode for remainder of project...*

This functionality therefore ensures, for instance, that the Security.evtx logs for the two specified machines are available in Elasticsearch before all other logs, allowing the responder to access critical data faster.

Furthermore, sometimes a responder will collect Event Logs from an IT environment to ensure that data is preserved, but will subsequently identify that their analysis needs to only focus on a few key machines.

Rather than have the responder move folders in order to run HELi in Directory Mode without ingesting the remaining data, you can instruct HELi to prioritise artefacts in strict mode:

```
./HELi.py -d ./logs -p AD-01,AD-02 -l Security.evtx,Application.evtx,System.evtx --strict
```

The above example will work exactly as the previous example, except it will not process any Event Logs outside of the three logs you have specified within `AD-01` and `AD-02`.

## Parameters

The tables below list the required and optional parameters HELi supports, alongside a description of their functionality.

#### Required

| Parameter   | Short Parameter | Description                                                  |
| ----------- | --------------- | ------------------------------------------------------------ |
| --file      | -f              | Specify the EVTX file to process in Individual File Mode with a relative or absolute path. On Linux systems, this parameter is case-sensitive. |
| --directory | -d              | Specify the folder to process in Directory Mode or Directory Mode with Prioritisations with a relative or absolute path. On Linux systems, this parameter is case-sensitive. |

#### Optional

| Parameter | Short Parameter | Default Value         | Description                                                  |
| --------- | --------------- | --------------------- | ------------------------------------------------------------ |
| --cores   | -c              | \# of cores supported | You can specify the number of cores to use during processing. If left blank, this value will default to the number of cores supported by your machine, as detected by the Python`multiprocessing.cpu_count()` function. |
| --buffer  | -b              | 1,000                 | Event Logs are processed and submitted to Elasticsearch in batches equal to the value of this parameter. The implications of how this value affects overall processing time are not fully understood, therefore, we recommend using the default value for now. |
| --index   | -i              | projectx              | This parameter specifies the destination Elasticsearch index for ingesting Event Logs. Remember that Elasticsearch indexes have naming restrictions, and only support lowercase characters. Refer [here](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-create-index.html) for more information. |
| --nodes   | -n              | 127.0.0.1:9200        | You can specify multiple Elasticsearch nodes, which HELi will cycle through if the first node returns an HTTP error code (such as `HTTP 429`) when uploading Event Logs. Use comma separated values if specifying more than one node, for example, `"10.0.0.1:9200,10.0.0.2:9200,10.0.0.3:9200"`. If you don't specify a value, HELi will assume there is an Elasticsearch index available on localhost. |
| --token   | -t              | None                  | Elasticsearch supports Basic Authentication. If you secure your Elasticsearch with a username and password you can provide these here in the format `USERNAME:PASSWORD`. The default setting is not to use Basic Authentication. |
| --pfolder | -p              | None                  | When processing a directory with subfolders, you can choose to prioritise certain subfolders and ensure they are processed first.<br /><br />You can specify multiple subfolders using comma separated values, and the order you list them in will be enforced, for example, "dc-01, dc-02, dc-03" will process `dc-01` first before moving on to `dc-02`, and so on. If you don't specify a value, subfolders will be processed in alphabetical order.<br /><br />When combined with the --prioritiselog parameter, this behaviour changes slightly. Refer to *Directory Mode with Prioritisations*. |
| --plog    | -l              | None                  | When processing a directory, you can choose to prioritise certain logs and ensure they are processed before all other files.<br /><br />You can specify multiple file names using comma separated values, and the order you list them in will be enforced, for example, "Security.evtx,Application.evtx" will process `Security.evtx` files first (across all folders) before moving on to `Application.evtx`. If you don't specify a value, files will be processed in alphabetical order. |
| --strict  | -s              | False                 | Used in conjunction with `--prioritisefolder` or `--prioritiselogs`, this parameter will ensure that only the files or folders you specified will be processed. Refer to *Directory Mode with Prioritisations* for more information on this behaviour. |
| --debug   | None            | False                 | Enabling the `--debug` flag will disable posting any data to Elasticsearch and will provide a more verbose project description banner. If used with `--prioritisefolder` or `--prioritiselogs`, the order of the files to process will be listed. |

# Known Issues and Next Steps

In most situations, HELi functions as expected. However, even such a small application as this is beget by small issues and desired improvements. 

## Limitations

### Windows Event Logs

Windows Event Logs are a complex and difficult beast to tame, and Microsoft seem to have done an incredible job of making them opaque and difficult to work with.

Because of this, a tool like HELi that interprets the XML data behind the EVTX file format (and refer [here](http://www.dfrws.org/sites/default/files/session-files/paper-introducing_the_microsoft_vista_log_file_format.pdf) if you're interested in how these files are constructed) is only ever going to be as good as the data we're provided. This is a problem because Microsoft occasionally "cheat" with their Event Logs and leave important information out of the XML, instead opting to hard code that information into their Event Viewer.

Taking an example, if we consider the Event Log below:

```xml
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
	
	<System>
		<Provider Name="Windows Error Reporting" />
		<EventID Qualifiers="0">1001</EventID>
		<Level>4</Level>
		<Task>0</Task>
		<Keywords>0x80000000000000</Keywords>
		<TimeCreated SystemTime="2019-09-19T04:37:30.000000000Z" />
		<EventRecordID>408810</EventRecordID>
		<Channel>Application</Channel>
		<Computer>example.com</Computer>
		<Security />
	</System>
	
	<EventData>
		<Data />
		<Data>0</Data>
		<Data>WindowsWcpOtherFailure3</Data>
		<Data>Not available</Data>
		<Data>0</Data>
		<Data>6.3.9600</Data>
		<Data>poq\poqsil.cpp</Data>
		<Data>ReportAndOrStopProcessesForFile</Data>
		<Data>2300</Data>
		<Data>80070005</Data>
		<Data>0xab102733</Data>
		<Data />
		<Data />
		<Data />
		<Data />
		<Data>C:\Windows\Logs\CBS\CBS.log</Data>
		<Data />
		<Data />
		<Data>0</Data>
		<Data>2fb52af3-da97-11e9-80f2-8c98f7db42e7</Data>
		<Data>262144</Data>
		<Data />
	</EventData>
	
</Event>
```

You will notice that the children of `EventData` do not contain a name or label to indicate what their value may represent. We therefore know that *262144* is a value within this Event Log, for instance, but we don't know what this could mean.

In the Event Viewer, however, these labels are provided:

```
Fault bucket , type 0
Event Name: WindowsWcpOtherFailure3
Response: Not available
Cab Id: 0

Problem signature:
P1: 6.3.9600
P2: poq\poqsil.cpp
P3: ReportAndOrStopProcessesForFile
P4: 2300
P5: 80070005
P6: 0xab102733
P7: 
P8: 
P9: 
P10: 

Attached files:
C:\Windows\Logs\CBS\CBS.log

These files may be available here:


Analysis symbol: 
Rechecking for solution: 0
Report Id: 2fb52af3-da97-11e9-80f2-8c98f7db42e7
Report Status: 262144
```

We can now see that the value *262144* is marked as the Report Status for this Event Log.

#### What does this mean?

The only way of resolving this issue would be to create an offline mapping of different Event Log types and reconcile them against this dataset before submitting them to Elasticsearch. However, this may negatively impact performance.

As a workaround, we have chosen to submit the data fields without labels anyway. The data will still be available within Elasticsearch and can be queried, but you will probably have to manually compare the Event Log against known samples or other examples found online to understand the significance of the data.

### Design Limitations

Reducing the processing time for Event Logs is a key objective of this project. Our efforts to improve HELi's overall speed has hit a bottleneck with parsing the Event Log XML data into a dictionary with the `xmltodict` library, which is a time-intensive operation.

We are investigating two design changes to increase the speed of this operation:

- **Moving HELi  to PyPy**, which initial testing has confirmed yields significant speed improvements. One key consideration here is that 64-bit PyPy is only supported on Linux systems, which means that a Windows-bound PyPy implementation of HELi could only support EVTX files that do not exceed 32-bit integers.

- **Develop our own Event Log XML parser in C++**. Parsing XML in C++ and calling the function from HELi would offer substantial speed improvements, most likely beyond that offered by PyPy.

## Known Issues

- [ ] **Processes occasionally idle**

  For an as-yet-unknown reason, the HELi processes sometimes idle during a project. Sending a Keyboard Interrupt (CTRL+C) resumes the processes without causing data loss.

- [ ] **Elasticsearch field limits easily exceeded**

  By default, Elasticsearch will only allow 1,000 unique fields within an index. Because there are so many fields across the different types of Event Logs it is very easy to exceed this limit.


  For now, this limit should be manually adjusted (refer [here](https://www.elastic.co/guide/en/elasticsearch/reference/current/mapping.html#mapping-limit-settings)), however, the longer term fix is to query the index to understand when we are approaching this limit and increase it on-the-fly.

## Improvements

- [x] ~~Implement XPath parsing of Event Log XML.~~
  - [ ] Release version with full PyPy support.
- [ ] Improve argument parsing and incorporate validation.
- [ ] Improve handling of empty or corrupted files.
- [ ] Provide prettier and more useful logging, including as an external log file.
- [ ] Choose how to handle various HTTP errors from Elasticsearch; terminate or continue?
- [ ] Move bulk uploads of Event Logs to a dedicated process to increase efficiency.
- [ ] Increase efficiency by processing small EVTX files in a single-core.
- [ ] Create an explicit mapping for Elasticsearch documents.
- [ ] Add support for timezone setting (currently assumes GMT +0).
- [ ] Generally clean the code and remove some inefficiencies!

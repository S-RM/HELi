#!/usr/bin/env python

import requests, json
from multiprocessing import Queue, queues
import lib.projectengine as projectengine
import threading

def core_posting_worker(queue, thread_count=2):

    # Start threads to push data to
    item_queue = Queue()
    threads = []
    for i in range(thread_count):
        t = threading.Thread(target=thread_worker, args=[item_queue,], name=i)
        t.start()
        threads.append(t)

    # Threads are active and listening for data, now we just push tasks to them as they come up
    while True:
        try:
            item = queue.get(True, 1) # Try for up to 1 sec to get data, else give up
            
            if item == "STOP":
                for i in range(thread_count):
                    item_queue.put("STOP")
                break
        
            else:
                item_queue.put(item)
                    
        except queues.Empty:
            pass

    for t in threads:
        t.join()

def thread_worker(item_queue):

    while True:
        try:
            item = item_queue.get() # Try for up to 1 sec to get data, else give up

            if item == "STOP":
                break

            elif item['type'] == "report":
                
                projectengine.report_progress(
                    item['data']['count_postedrecord'],
                    item['data']['num_items']
                )

            elif item['type'] == "post":
                postToElastic(
                    item['data']['events'],
                    item['data']['index'],
                    item['data']['nodes'],
                    item['data']['token']
                )

        except queues.Empty:
            pass

def postToElastic(events, index, nodes, token=b""):

    # Start the node fault-tolerance
    currentNode = 0

    # Continuously attempt to post to nodes; when one fails, try the next if listed
    success = False
    results = {}
    count = 0
    headers = {}
    headers['content-type'] = "application/x-ndjson"
    if token != "":
        headers['Authorization'] = "Basic " + token.decode('ascii')

    while not success:
        try:
            # Post to current node
            results = requests.post(nodes[currentNode], data=events, headers=headers)

            if results.status_code == 200:
                success = True
            else:
               print(json.dumps(results.json(), indent=4))
               break

        except Exception as e:
            print(str(e))





#!/usr/bin/python3

import sys
import requests
import json
import subprocess
import csv
import os
import hashlib
from datetime import datetime
import configparser
from random import randint
import collections

def getDigest(input):
    print(input)
    block_size = 65536
    sha256 = hashlib.sha256()
    sha256.update(input.encode('utf-8'))
    digest = sha256.hexdigest()
    return(digest)

def lineAddScanID(line, scanid):
    columns = line.split(' ')
    newline = ""
    if (len(columns) > 1):
        columns[-2] = str(columns[-2]) + ',scanid="' + str(scanid) + '"'
        newline += ' '.join(columns)
    return newline

def LimeScan (url, configurl, devicename, deviceconfig):
    if deviceconfig['custom_config'] is None:
        params = "-f 600M:1000M -C 0 -A LNAW -w 35M -r 16M -OSR 8 -b 512 -g 48 -n 64 -T 1"
    else:
        params = deviceconfig['custom_config']
    subprocess.Popen(["LimeScan " + params + " -O 'scan-output'"], shell=True).wait()

    first_timestamp = None
    last_timestamp = None
    with open('scan-output/scan-outputPk.csv', newline='') as csvfile:
        reader = csv.reader(csvfile, delimiter=',')
        reader.__next__() #first row is filename, skip it
        i = 1
        lines = ""
        for items in reader:
            timestamp_obj = datetime.strptime(items[0].strip() + " " + items[1].strip(), '%Y-%m-%d %H:%M:%S')
            nanoseconds = str(round(timestamp_obj.timestamp() * 1e9) + i)
            if first_timestamp is None:
                first_timestamp = nanoseconds
            freqLow = str(int(float(items[2]) * 1e6))
            freqHigh = str(int(float(items[3]) * 1e6))
            freqStep = str(int(float(items[4])))
            dB = '"' + ",".join([str(item).strip() for item in items[6:]]) + '"'
            influxline = "power,sensor=" + devicename + " hzlow=" + freqLow + ",hzhigh=" + freqHigh + ",step=" + freqStep + ",samples=3,dbs=" + dB + " " + nanoseconds
            lines += '\n' + influxline
            last_timestamp = nanoseconds
            i += 1

        scan_digest = getDigest(lines)
        metadata = {
            "device_config_id": deviceconfig['device_config_id'],
            "scan_start_time": float(first_timestamp),
            "scan_finish_time": float(last_timestamp),
            "scan_digest": scan_digest
        }

        scanid = getDigest(json.dumps(metadata, sort_keys=True))
        metadata["id"] = scanid

        influxlines = ""
        for line in lines.split('\n'):
            influxlines += lineAddScanID(line, scanid) + '\n'
        influx_response = requests.post(url, data=influxlines)
        sqlite_response = requests.post(configurl + "scans", json = metadata)


def GSM (url, configurl, devicename, deviceconfig):
    band = "GSM900"
    if deviceconfig['scan_band'] is not None:
        band = deviceconfig['scan_band']
    params = "-s0.8e6 -g56 -f 20000000 -O /tmp/scan-outputGSM -b " + band
    first_timestamp = datetime.now().timestamp() * 1e9
    subprocess.Popen(["grgsm_scanner " + params], shell=True).wait()
    print("command:", "grgsm_scanner " + params)

    last_timestamp = datetime.now().timestamp() * 1e9
    lines = ""
    items = []

    with open('/tmp/scan-outputGSM') as resultsfile:
        dummysplit = resultsfile.readlines()
        for item in dummysplit:
            subitems = {}
            print(item)
            commasplit = item.split(',')
            commasplit = [i.split(':') for i in commasplit]
            for i in commasplit:
                if i != "" and i[0] and i[1]:
                    subitems[i[0].strip()] = i[1].strip()
            try:
                if subitems['ARFCN'] and int(subitems['ARFCN']) > 0 and int(subitems['MCC']) > 0 and int(subitems['LAC']) > 0 and int(subitems['CID']) > 0 and int(subitems['MNC']) > 0 and (int(subitems['Pwr']) > 0 or int(subitems['Pwr']) < 0):
                    items.append(subitems)
                    current_timestamp = str(round(datetime.now().timestamp() * 1e9))
                    influxline = 'gsm,sensor=' + devicename + ',ARFCN=' + subitems['ARFCN'] + ',CID=' + subitems['CID'] + ',LAC=' + subitems['LAC'] + ',MCC=' + subitems['MCC'] + ',MNC=' + subitems['MNC'] + ',band=' + band + ' Pwr=' + subitems['Pwr'] + " " + current_timestamp
                    lines += '\n' + influxline
            except:
                continue

    for line in lines.split('\n'):
        line = line.strip()
        print(line)
        scan_digest = getDigest(line)
        metadata = {
            "device_config_id": deviceconfig['device_config_id'],
            "scan_start_time": first_timestamp,
            "scan_finish_time": last_timestamp,
            "scan_digest": scan_digest
        }
        scanid = getDigest(json.dumps(metadata, sort_keys=True))
        metadata["id"] = scanid
        line = lineAddScanID(line, scanid)
        print(line)
        influx_response = requests.post(url, data=line)
        sqlite_response = requests.post(configurl + "scans", json = metadata)

config = configparser.ConfigParser()
configfile = config.read(['config.ini', '/pantavisor/user-meta/limescan-config.ini'])
if len(configfile) == 0:
    raise ValueError("Configuration file missing, rename config.example.ini to config.ini")

url = config["DEFAULT"]["DATA_URL"] + "write?db=limescan"
configurl = config["DEFAULT"]["API_URL"]
devicename = config["DEFAULT"]["DEVICE_NAME"]

deviceconfig = json.loads(requests.get(configurl + "devices/" + devicename).text)

if deviceconfig['scan_type'] == "power":
    LimeScan(url, configurl, devicename, deviceconfig)

if deviceconfig['scan_type'] == "gsm":
    GSM(url, configurl, devicename, deviceconfig)


#!/usr/bin/env python3
"""
Copyright IBM Corporation 2018

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import json
import pathlib
import re
import socket

SCALE_CLUSTER_DEFINITION_PATH = "/vars/scale_clusterdefinition.json"
CLUSTER_DEFINITION_JSON = {"node_details": [], "scale_storage": []}


def read_tf_inv_file(tf_inv_path):
    """ Read the terraform inventory file """
    tf_inv_list = open(tf_inv_path).read().splitlines()
    return tf_inv_list


def parse_tf_in_json(tf_inv_list):
    """ Parse terraform inventory and prepare dict """
    raw_body, compute_ips, storage_disk_map, az_list = {}, [], {}, []
    for each_line in tf_inv_list:
        key_val_match = re.match('(.*)=(.*)', each_line)
        if key_val_match:
            if key_val_match.group(1) == "availability_zones":
                # Ex: "[sa-east-1a,sa-east-1b]"
                az_list = re.findall(r'(\w+-\w+-\w+)', key_val_match.group(2))
                raw_body[key_val_match.group(1)] = az_list
            elif key_val_match.group(1) == "compute_instances_by_ip":
                # Ex: "[10.0.2.214,10.0.2.216]"
                compute_ips = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})',
                                         key_val_match.group(2))
                raw_body[key_val_match.group(1)] = compute_ips
            elif key_val_match.group(1) == "compute_instance_desc_map":
                # Ex: "{10.0.7.157:[/dev/xvdf]}"
                desc_match = re.match(r'{(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):\[(.*)\]}',
                                      key_val_match.group(2))
                raw_body[key_val_match.group(1)] = {desc_match.group(1): desc_match.group(2)}
            elif key_val_match.group(1) == "storage_instance_disk_map":
                # Ex: "{10.0.30.220:[/dev/xvdf],10.0.8.162:[/dev/xvdf]}"}
                raw_storage_disk_map = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):\[(.*?)\]',
                                                  key_val_match.group(2))
                for each_storage_instance in raw_storage_disk_map:
                    storage_disk_map[each_storage_instance[0]] = each_storage_instance[1].split(",")
                raw_body[key_val_match.group(1)] = storage_disk_map
            else:
                raw_body[key_val_match.group(1)] = key_val_match.group(2)

    return raw_body


def initialize_node_details(fqdn, ip_address, ansible_ssh_private_key_file, is_nsd_server,
                            is_quorum_node=False, is_manager_node=False, is_gui_node=False):
    """ Initialize node details for cluster definition.
    :args: json_data (json), fqdn (string), ip_address (string),
           is_nsd_server (bool), is_quorum_node (bool),
           is_manager_node (bool), is_gui_node (bool)
    :return: json_data (json)
    """
    CLUSTER_DEFINITION_JSON['node_details'].append({'fqdn': fqdn,
                                                    'ip_address': ip_address,
                                                    'ansible_ssh_private_key_file': ansible_ssh_private_key_file,
                                                    'state': 'present',
                                                    'is_nsd_server': is_nsd_server,
                                                    'is_quorum_node': is_quorum_node,
                                                    'is_manager_node': is_manager_node,
                                                    'is_gui_node': is_gui_node})


if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(description='Convert terraform inventory '
                                                 'to ansible inventory format '
                                                 'install and configuration.')
    PARSER.add_argument('--tf_inv_path', required=True,
                        help='Terraform inventory file path')
    PARSER.add_argument('--ansible_scale_repo_path', required=True,
                        help='ibm-spectrum-scale-install-infra repository path')
    PARSER.add_argument('--ansible_ssh_private_key_file', required=True,
                        help='Ansible SSH private key file (Ex: /root/tf_data_path/id_rsa)')
    PARSER.add_argument('--verbose', action='store_true',
                        help='print log messages')
    ARGUMENTS = PARSER.parse_args()

    RAW_TF_INV = read_tf_inv_file(ARGUMENTS.tf_inv_path)
    TF_INV = parse_tf_in_json(RAW_TF_INV)
    if ARGUMENTS.verbose:
        print("Parsed terraform output: %s" % json.dumps(TF_INV, indent=4))
    total_node_count = len(TF_INV['compute_instances_by_ip']) + \
        len(TF_INV['compute_instance_desc_map'].keys()) + \
        len(TF_INV['storage_instance_disk_map'].keys())
    if ARGUMENTS.verbose:
        print("Total node count: ", total_node_count)

    # Determine total number of quorum, manager nodes to be in the cluster
    quorum_count, manager_count = 0, 3
    if total_node_count < 4:
        quorum_count = total_node_count
    elif 4 <= total_node_count < 10:
        quorum_count = 3
    elif 10 <= total_node_count < 19:
        quorum_count = 5
    else:
        quorum_count = 7

    if ARGUMENTS.verbose:
        print("Total quorum count: ", quorum_count)

    # Storage/NSD nodes to be quorum nodes
    for each_ip in TF_INV['storage_instance_disk_map']:
        if list(TF_INV['storage_instance_disk_map'].keys()).index(each_ip) <= (manager_count - 1):
            initialize_node_details(socket.getfqdn(each_ip), each_ip,
                                    ansible_ssh_private_key_file=ARGUMENTS.ansible_ssh_private_key_file,
                                    is_nsd_server=True, is_quorum_node=True, is_manager_node=True)
        else:
            initialize_node_details(socket.getfqdn(each_ip), each_ip,
                                    ansible_ssh_private_key_file=ARGUMENTS.ansible_ssh_private_key_file,
                                    is_nsd_server=True, is_quorum_node=True, is_manager_node=False)

    # Compute desc node to be quorum nodes
    for each_ip in TF_INV['compute_instance_desc_map']:
        initialize_node_details(socket.getfqdn(each_ip), each_ip,
                                ansible_ssh_private_key_file=ARGUMENTS.ansible_ssh_private_key_file,
                                is_nsd_server=True, is_quorum_node=True, is_manager_node=True)

    quorums_left = quorum_count - len(TF_INV['storage_instance_disk_map'].keys()) - \
        len(TF_INV['compute_instance_desc_map'].keys())

    if ARGUMENTS.verbose:
        print("Total quorums left and to be assigned to compute nodes: ", quorums_left)

    # Additional quorums assign to compute nodes
    if quorums_left:
        for each_ip in TF_INV['compute_instances_by_ip'][0:quorums_left]:
            initialize_node_details(socket.getfqdn(each_ip), each_ip,
                                    ansible_ssh_private_key_file=ARGUMENTS.ansible_ssh_private_key_file,
                                    is_nsd_server=False, is_quorum_node=True, is_manager_node=False)
        for each_ip in TF_INV['compute_instances_by_ip'][quorums_left:]:
            initialize_node_details(socket.getfqdn(each_ip), each_ip,
                                    ansible_ssh_private_key_file=ARGUMENTS.ansible_ssh_private_key_file,
                                    is_nsd_server=False, is_quorum_node=False, is_manager_node=False)

    if not quorums_left:
        for each_ip in TF_INV['compute_instances_by_ip']:
            initialize_node_details(socket.getfqdn(each_ip), each_ip,
                                    ansible_ssh_private_key_file=ARGUMENTS.ansible_ssh_private_key_file,
                                    is_nsd_server=False, is_quorum_node=False, is_manager_node=False)

    # Map storage nodes to failure groups based on AZ and subnet variations
    failure_group1, failure_group2 = [], []
    if len(TF_INV['availability_zones']) == 1:
        # Single AZ, just split list equally
        num_storage_nodes = len(list(TF_INV['storage_instance_disk_map']))
        mid_index = num_storage_nodes//2
        failure_group1 = list(TF_INV['storage_instance_disk_map'])[:mid_index]
        failure_group2 = list(TF_INV['storage_instance_disk_map'])[mid_index:]
    else:
        # Multi AZ, split based on subnet match
        subnet_pattern = re.compile(r'\d{1,3}\.\d{1,3}\.(\d{1,3})\.\d{1,3}')
        subnet1A = subnet_pattern.findall(list(TF_INV['storage_instance_disk_map'])[0])
        for each_ip in TF_INV['storage_instance_disk_map']:
            current_subnet = subnet_pattern.findall(each_ip)
            if current_subnet[0] == subnet1A[0]:
                failure_group1.append(each_ip)
            else:
                failure_group2.append(each_ip)

    # Prepare dict of disks / NSD list
    disks_list, nsd_index = [], 0
    for each_ip, disk_per_ip in TF_INV['storage_instance_disk_map'].items():
        if each_ip in failure_group1:
            for each_disk in disk_per_ip:
                nsd_index += 1
                disks_list.append({"device": each_disk, "nsd": "nsd%s" % nsd_index,
                                   "failureGroup": 1, "servers": each_ip,
                                   "usage": "dataAndMetadata", "pool": "system"})
        if each_ip in failure_group2:
            for each_disk in disk_per_ip:
                nsd_index += 1
                disks_list.append({"device": each_disk, "nsd": "nsd%s" % nsd_index,
                                   "failureGroup": 2, "servers": each_ip,
                                   "usage": "dataAndMetadata", "pool": "system"})

    # Append "descOnly" disk details
    disks_list.append({"device": list(TF_INV['compute_instance_desc_map'].values())[0],
                       "nsd": "desconlynsd",
                       "failureGroup": 3,
                       "servers": list(TF_INV['compute_instance_desc_map'].keys())[0],
                       "usage": "descOnly", "pool": "system"})

    # Populate "scale_storage" list
    CLUSTER_DEFINITION_JSON["scale_storage"].append({"filesystem": pathlib.PurePath(TF_INV['filesystem_mountpoint']).name,
                                                     "blockSize": TF_INV['filesystem_block_size'],
                                                     "defaultDataReplicas": len(TF_INV['availability_zones']),
                                                     "defaultMetadataReplicas": 2,
                                                     "automaticMountOption": "true",
                                                     "defaultMountPoint": TF_INV['filesystem_mountpoint'],
                                                     "disks": disks_list})

    if ARGUMENTS.verbose:
        print("Content of scale_clusterdefinition.json: ",
              json.dumps(CLUSTER_DEFINITION_JSON, indent=4))

    # Write json content
    if ARGUMENTS.verbose:
        print("Writing cloud infrastructure details to: ",
              ARGUMENTS.ansible_scale_repo_path.rstrip('/') + SCALE_CLUSTER_DEFINITION_PATH)
    with open(ARGUMENTS.ansible_scale_repo_path.rstrip('/') + SCALE_CLUSTER_DEFINITION_PATH, 'w') as json_fh:
        json.dump(CLUSTER_DEFINITION_JSON, json_fh, indent=4)
    if ARGUMENTS.verbose:
        print("Completed writing cloud infrastructure details to: ",
              ARGUMENTS.ansible_scale_repo_path.rstrip('/') + SCALE_CLUSTER_DEFINITION_PATH)

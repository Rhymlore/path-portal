import re

try:  # py3
    from configparser import ConfigParser
except ImportError:  # py2
    from ConfigParser import ConfigParser

from typing import Dict, List
import xml.etree.ElementTree as ET
import http.client
import urllib.error
import urllib.request

from flask import current_app, request

from .exceptions import ConfigurationError

TOPOLOGY_RG = "https://topology.opensciencegrid.org/rgsummary/xml"
SERVICE_MAPPING = {'Submit Node': 109,
                   'Execution Endpoint': 157}

def get_user_info():
    try:
        return current_app.config["USER_INFO_FAKE"]
    except:
        pass

    result = {
        "idp": request.environ.get("OIDC_CLAIM_idp_name", None),
        "id": request.environ.get("OIDC_CLAIM_osgid", None),
        "name": request.environ.get("OIDC_CLAIM_name", None),
        "email": request.environ.get("OIDC_CLAIM_email", None)
    }

    current_app.logger.debug("Authenticated user info is {}".format(str(result)))

    return result


def is_signed_up(user_info):
    return user_info.get("id")


def get_access_point_fqdns(user_info: Dict) -> List[str]:
    """Return a list of access point FQDNs administered by the user
    """
    return get_sources(user_info, 'Submit Node')


def get_execution_endpoint_fqdns(user_info: Dict) -> List[str]:
    """Return a list of execution endpoint FQDNs administered by the user
    """
    return get_sources(user_info, 'Execution Endpoint')


def get_sources(user_info: Dict, topology_service: str):
    """
    Query topology to get a list of FQDNs for active resources administered by the user
    """
    osgid = user_info.get("id")
    if not osgid:
        return []
    # URL for all Execution Endpoint and Submit Node (access points) resources
    topology_url = TOPOLOGY_RG + f'?service=on&service_{SERVICE_MAPPING[topology_service]}=on'
    try:
        response = urllib.request.urlopen(topology_url)
        topology_xml = response.read()
    except (urllib.error.URLError, http.client.HTTPException):
        raise TopologyError('Error retrieving OSG Topology registrations')

    try:
        topology_et = ET.fromstring(topology_xml)
    except ET.ParseError:
        if not topology_xml:
            msg = 'OSG Topology query returned empty response'
        else:
            msg = 'OSG Topology query returned malformed XML'
        raise TopologyError(msg)

    os_pool_resources = []
    resources = topology_et.findall('./ResourceGroup/Resources/Resource')
    if not resources:
        raise TopologyError('Failed to find any OSG Topology resources')

    for resource in resources:
        try:
            fqdn = resource.find('./FQDN').text.strip()
        except AttributeError:
            # skip malformed resource missing an FQDN
            continue

        active = False
        try:
            active = resource.find('./Active').text.strip().lower() == "true"
        except AttributeError:
            continue
        if not active:
            continue

        try:
            services = [service.find("./Name").text.strip()
                        for service in resource.findall("./Services/Service")]
        except AttributeError:
            continue
        if topology_service not in services:
            continue

        try:
            admin_contacts = [contact_list.find('./Contacts')
                              for contact_list in resource.findall('./ContactLists/ContactList')
                              if contact_list.findtext('./ContactType', '').strip() == 'Administrative Contact']
        except AttributeError:
            # skip malformed resource missing contacts
            continue

        for contact_list in admin_contacts:
            for contact in contact_list.findall("./Contact"):
                if contact.findtext('./CILogonID', '').strip() == osgid:
                    os_pool_resources.append(fqdn)

    return os_pool_resources


SOURCE_CHECK = re.compile(r"^[a-zA-Z][-.0-9a-zA-Z]*$")

def is_valid_source_name(source_name):
    return bool(SOURCE_CHECK.match(source_name))

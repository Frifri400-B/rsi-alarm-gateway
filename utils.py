import logging
from Crypto.Cipher import AES
from Crypto import Random
import codecs
import json
import traceback

decode_hex = codecs.getdecoder("hex_codec")


#https://cybergibbons.com/alarms-2/multiple-serious-vulnerabilities-in-rsi-videofieds-alarm-protocol/
def generate_preshared_key(serial):
    return (
        serial[4] + '0' + serial[15] + serial[11] + '0' + serial[5] +
        serial[13] + serial[6] + serial[8] + serial[12] + serial[7] +
        serial[14] + '1' + '0' + serial[10] + serial[9] + serial[7] +
        serial[10] + serial[4] + serial[15] + serial[13] + serial[6] +
        serial[12] + '0' + serial[8] + '0' + serial[14] + '1' +
        serial[11] + serial[11] + '0' + serial[5]
    )


def delete_x1a(string):
    if string.endswith('\x1a'):
        return string[:-1]
    return string


def get_challenge_response(key, challenge):
    cipher = AES.new(decode_hex(key)[0], AES.MODE_ECB)
    return cipher.encrypt(decode_hex(challenge)[0]).hex().upper()


_recv_buffers = {}

def recv_message(conn):
    import socket as _socket
    key = id(conn)
    if key not in _recv_buffers:
        _recv_buffers[key] = b""

    while b'\x1a' not in _recv_buffers[key]:
        try:
            chunk = conn.recv(4096)
        except _socket.timeout:
            raise
        if not chunk:
            _recv_buffers.pop(key, None)
            raise ConnectionError("Connection closed by peer")
        _recv_buffers[key] += chunk

    idx = _recv_buffers[key].index(b'\x1a')
    msg = _recv_buffers[key][:idx].decode(errors='replace')
    _recv_buffers[key] = _recv_buffers[key][idx + 1:]
    return msg


def clear_recv_buffer(conn):
    _recv_buffers.pop(id(conn), None)


def client_auth(conn):
    conn.send(b"IDENT,1000\x1a")

    raw = recv_message(conn)
    logging.info("Auth recv: %s" % raw)
    parts = raw.split(',')
    if parts[0] != 'IDENT' or len(parts) < 2:
        logging.error("Expected IDENT response, got: %s" % raw)
        return False, None, None

    serial = parts[1]
    logging.info("serial: %s" % serial)
    key = generate_preshared_key(serial)
    logging.info("key: %s" % key)

    conn.send(('SETKEY,' + key + '\x1a').encode())

    conn.send(b"VERSION,2,0\x1a")

    challenge = Random.new().read(16).hex().upper()
    logging.info("Server challenge: %s" % challenge)
    conn.send(('AUTH1,' + challenge + '\x1a').encode())

    raw = recv_message(conn)
    logging.info("Auth recv: %s" % raw)
    parts = raw.split(',')
    if parts[0] != 'AUTH2' or len(parts) < 3:
        logging.error("Expected AUTH2, got: %s" % raw)
        return False, None, None

    panel_challenge = delete_x1a(parts[2])
    response = get_challenge_response(key, panel_challenge)
    logging.info("Key response to alarm: %s" % response)

    conn.send(('AUTH3,' + response + '\x1a').encode())

    raw = recv_message(conn)
    logging.info("Auth recv: %s" % raw)
    if 'AUTH_SUCCESS' in raw:
        logging.info("Authentication successful!")
        return True, serial, key

    logging.error("Authentication failed, got: %s" % raw)
    return False, None, None


def read_config(config):
    with open(config, 'r') as file:
        return json.load(file)


#https://resideo.kayako.com/article/561-events-list-frontel
EVENT_TYPE_MAP = {
    "1":  "intrusion",
    "3":  "tamper",
    "5":  "panic",
    "24": "armed",
    "25": "disarmed",
    "29": "alarmTest",
    "32": "panicSmoke",
    "34": "panicMedical",
}


def parse_event_homebridge(event_data_list):
    code = event_data_list[0] if event_data_list else "unknown"
    event_type = EVENT_TYPE_MAP.get(code, "unknown")

    result = {
        "type":         event_type,
        "raw_code":     code,
        "peripheral":   None,
        "detector":     None,
        "arming_profile": None,
        "code_or_badge":  None,
        "mqtt_state":   None,
        "alarm_state":  None,
    }

    if code == "1":   # intrusion
        result["peripheral"] = event_data_list[1] if len(event_data_list) > 1 else None
        result["detector"]   = event_data_list[2] if len(event_data_list) > 2 else None
        result["mqtt_state"]  = "triggered"
        result["alarm_state"] = "triggered"

    elif code == "3":  # tamper
        result["peripheral"] = event_data_list[1] if len(event_data_list) > 1 else None
        result["detector"]   = event_data_list[2] if len(event_data_list) > 2 else None
        result["mqtt_state"]  = "triggered"
        result["alarm_state"] = "triggered"

    elif code in ("5", "32", "34"):  # panic, panicSmoke, panicMedical
        result["peripheral"] = event_data_list[1] if len(event_data_list) > 1 else None
        result["mqtt_state"]  = "triggered"
        result["alarm_state"] = "triggered"

    elif code == "24":  # armed
        result["arming_profile"] = event_data_list[1] if len(event_data_list) > 1 else None
        result["code_or_badge"]  = event_data_list[2] if len(event_data_list) > 2 else None
        result["mqtt_state"]  = "armed_away"
        result["alarm_state"] = "armed"

    elif code == "25":  # disarmed
        result["arming_profile"] = event_data_list[1] if len(event_data_list) > 1 else None
        result["code_or_badge"]  = event_data_list[2] if len(event_data_list) > 2 else None
        result["mqtt_state"]  = "disarmed"
        result["alarm_state"] = "disarmed"

    elif code == "29":  # alarmTest
        result["mqtt_state"]  = "triggered"
        result["alarm_state"] = "triggered"

    else:
        result["mqtt_state"]  = "unknown"
        result["alarm_state"] = None

    return result


def find_event_type(event, cfg):
    try:
        event_array = event.split(',')
        event_type = cfg["mapping_events"][event_array[1]]
        source_of_event = None
        zone_of_event = None
        try:
            if "device_index" in event_type.keys():
                source_of_event = cfg["device_index"][event_array[2]].get("name")
                if "zone" in cfg["device_index"][event_array[2]].keys():
                    zone_id = cfg["device_index"][event_array[2]].get("zone")
                    zone_of_event = cfg["zones"][str(zone_id)].get("name")
            elif "mapping_users" in event_type.keys():
                source_of_event = cfg["mapping_users"][event_array[3]]
        except:
            logging.error("unable to find source of event (%s)" % event)
            traceback.print_exc()
        event_type["source_event"] = source_of_event
        event_type["zone_event"] = zone_of_event
        return event_type
    except:
        logging.error("unable to find event type (%s)" % event)
        traceback.print_exc()
        return None

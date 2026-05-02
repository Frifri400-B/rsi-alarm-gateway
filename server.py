# coding: utf-8

from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR
import logging
import sys
import traceback
import threading
import time
import os

from utils import (
    generate_preshared_key, delete_x1a, client_auth, recv_message, clear_recv_buffer,
    read_config, find_event_type, parse_event_homebridge
)
from mqtt import (
    mqtt_start_server, mqtt_ha_discovery,
    mqtt_publish_alarm_state, mqtt_publish_sensor,
    HA_CMD_DISARM, HA_CMD_ARM_AWAY, HA_CMD_ARM_HOME, HA_CMD_ARM_NIGHT,
    HA_STATE_DISARMED, HA_STATE_ARMED_AWAY, HA_STATE_TRIGGERED,
    HA_STATE_ARMING, HA_STATE_PENDING,
    ALARM_STATE_TOPIC, ALARM_COMMAND_TOPIC
)

try:
    os.environ["LOGLEVEL"]
except KeyError:
    print("Please set the environment variable LOGLEVEL")
    sys.exit(1)

log = logging.getLogger()
out_hdlr = logging.StreamHandler()
out_hdlr.setFormatter(logging.Formatter('[%(asctime)s] - %(module)s - %(levelname)s - %(message)s'))
out_hdlr.setLevel(logging.os.environ["LOGLEVEL"])
log.addHandler(out_hdlr)
log.setLevel(logging.os.environ["LOGLEVEL"])


class AlarmState:
    def __init__(self):
        self.lock = threading.Lock()
        self._state = HA_STATE_DISARMED
        self.connection = None
        self.authenticated = False

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        with self.lock:
            self._state = value

    def send_to_panel(self, msg):
        with self.lock:
            if self.connection and self.authenticated:
                try:
                    self.connection.send((msg + '\x1a').encode())
                    logging.info("Sent to panel: %s" % msg)
                    return True
                except Exception:
                    logging.error("Failed to send message to panel")
                    traceback.print_exc()
            else:
                logging.warning("Panel not connected/authenticated, cannot send: %s" % msg)
        return False

    def arm(self):
        return self.send_to_panel("ARMING,1")

    def disarm(self):
        return self.send_to_panel("ARMING,0")

alarm_state = AlarmState()


def on_mqtt_command(cmd, mqtt_client, cfg):
    logging.info("HA command received: %s" % cmd)

    if cmd == HA_CMD_DISARM:
        if alarm_state.disarm():
            logging.info("Disarm command sent to panel")
        else:
            logging.warning("Disarm failed (panel not connected?)")

    elif cmd in (HA_CMD_ARM_AWAY, HA_CMD_ARM_HOME, HA_CMD_ARM_NIGHT):
        mqtt_publish_alarm_state(mqtt_client, cfg, HA_STATE_ARMING)
        alarm_state.state = HA_STATE_ARMING
        logging.info("State → arming (command: %s)" % cmd)
        if alarm_state.arm():
            logging.info("Arm command sent to panel (%s)" % cmd)
        else:
            logging.warning("Arm failed (panel not connected?)")
            mqtt_publish_alarm_state(mqtt_client, cfg, HA_STATE_DISARMED)
            alarm_state.state = HA_STATE_DISARMED

    else:
        logging.warning("Unknown HA command: %s" % cmd)

def main():
    try:
        cfg = read_config("config.json")
        start_alarm_server(cfg)
    except KeyError:
        print("Please add config.json")
        sys.exit(1)

def start_alarm_server(cfg):
    host = cfg["socket_bind"]
    port = cfg["socket_listen_port"]

    soc = socket(AF_INET, SOCK_STREAM)
    soc.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    logging.info("Socket created")
    try:
        soc.bind((host, port))
    except Exception:
        logging.error(str(sys.exc_info()))
        sys.exit()
    try:
        mqtt_client = mqtt_start_server(
            cfg,
            command_callback=lambda cmd: on_mqtt_command(cmd, mqtt_client, cfg)
        )
        if cfg.get("home_assistant_integration"):
            mqtt_ha_discovery(mqtt_client, cfg)
        mqtt_publish_alarm_state(mqtt_client, cfg, HA_STATE_DISARMED)
    except Exception:
        logging.error("MQTT startup failed")
        traceback.print_exc()
        sys.exit()
    soc.listen(5)
    logging.info("Socket now listening on %s:%s" % (host, port))
    while True:
        connection, address = soc.accept()
        ip, port_client = str(address[0]), str(address[1])
        logging.info("### Connected with %s:%s ###" % (ip, port_client))
        try:
            t = threading.Thread(
                target=client_thread,
                args=(connection, ip, port_client, mqtt_client, cfg),
                daemon=True
            )
            t.start()
        except Exception:
            logging.error("Thread did not start.")
            traceback.print_exc()
    soc.close()


def client_thread(connection, ip, port, mqtt_client, cfg, max_buffer_size=5120):
    logging.info("Start new thread: %s" % threading.get_ident())
    logging.info("Number of threads: %s" % threading.active_count())
    is_active = True
    connection.settimeout(10)
    success, serial, key = client_auth(connection)
    if not success:
        logging.info("Authentication failed — closing connection %s:%s" % (ip, port))
        connection.close()
        return
    alarm_state.connection = connection
    alarm_state.authenticated = True
    logging.info("Panel authenticated (serial: %s)" % serial)
    heartbeat_stop = threading.Event()

    def heartbeat():
        while not heartbeat_stop.wait(60):
            logging.info("Sending heartbeat STATUS to keep panel connected")
            alarm_state.send_to_panel("STATUS")
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    import socket as _socket
    while is_active:
        try:
            message = recv_message(connection)
        except _socket.timeout:
            continue
        except Exception:
            logging.info("Panel disconnected — closing connection %s:%s" % (ip, port))
            break
        logging.debug("Received: %s" % message)
        parts = message.split(',') if ',' in message else [message]
        event_type = parts[0]
        event_data = parts[1:]

        if event_type == "ALARM":
            logging.warning("ALARM received from panel, sending ALARM_ACK")
            connection.send(b"ALARM_ACK\x1a")

        elif event_type == "LOG":
            logging.info("LOG received, sending LOG_ACK")
            connection.send(b"LOG_ACK\x1a")

        elif event_type == "FILE":
            logging.info("FILE received")
            file_msg = recv_message(connection)
            if 'FileVersion' in file_msg:
                logging.info("JSON file received, sending FILE_ACK")
                connection.send(b"FILE_ACK\x1a")

        elif event_type == "REQACK":
            logging.info("REQACK received, sending ACK")
            connection.send(b"ACK\x1a")

        elif event_type == "ARMING":
            logging.info("ARMING confirmation from panel: %s" % event_data)

        elif event_type == "EVENT":
            logging.info("EVENT received: %s" % message)
            _handle_event(event_data, message, mqtt_client, cfg)

        elif event_type.startswith("OUTPUT"):
            logging.debug("OUTPUT data received from panel (ignored)")

        else:
            logging.debug("Unknown message type: %s" % event_type)

    heartbeat_stop.set()
    alarm_state.connection = None
    alarm_state.authenticated = False
    clear_recv_buffer(connection)
    connection.close()
    logging.info("### Connection %s:%s closed ###" % (ip, port))

def _handle_event(event_data, raw_message, mqtt_client, cfg):
    parsed = parse_event_homebridge(event_data)
    logging.info("Parsed event: type=%s state=%s peripheral=%s" % (
        parsed["type"], parsed["mqtt_state"], parsed["peripheral"]
    ))
    new_state = parsed.get("mqtt_state")
    if new_state:
        alarm_state.state = new_state
        mqtt_publish_alarm_state(mqtt_client, cfg, new_state)
    try:
        event_config = find_event_type(raw_message, cfg)
        if event_config:
            topic = "%s/%s/%s/state" % (
                cfg["mqtt_prefix"],
                cfg["home_assistant_sensors"][event_config["type"]]["sensor_type"],
                event_config["type"]
            )
            mqtt_publish_sensor(mqtt_client, cfg, event_config["type"], event_config["state"])
            src_key = event_config["type"] + "_source"
            if (
                src_key in cfg.get("home_assistant_sensors", {})
                and event_config.get("source_event")
                and event_config["source_event"] != "None"
            ):
                mqtt_publish_sensor(mqtt_client, cfg, src_key, event_config["source_event"])
            logging.info(
                "MQTT update: event=%s source=%s zone=%s" % (
                    event_config.get("comment"),
                    event_config.get("source_event"),
                    event_config.get("zone_event")
                )
            )
    except Exception:
        logging.error("Error publishing sensor state for event: %s" % raw_message)
        traceback.print_exc()

if __name__ == "__main__":
    main()

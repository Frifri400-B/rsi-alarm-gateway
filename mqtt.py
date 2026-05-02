import logging
import json
import paho.mqtt.client as mqtt


DEVICE_ID            = "rsi_videofied_alarm"
ALARM_STATE_TOPIC    = "rsi_alarm/alarm/state"
ALARM_COMMAND_TOPIC  = "rsi_alarm/alarm/set"

HA_STATE_DISARMED    = "disarmed"
HA_STATE_ARMED_AWAY  = "armed_away"
HA_STATE_ARMED_HOME  = "armed_home"
HA_STATE_ARMED_NIGHT = "armed_night"
HA_STATE_TRIGGERED   = "triggered"
HA_STATE_PENDING     = "pending"
HA_STATE_ARMING      = "arming"

HA_CMD_DISARM        = "DISARM"
HA_CMD_ARM_AWAY      = "ARM_AWAY"
HA_CMD_ARM_HOME      = "ARM_HOME"
HA_CMD_ARM_NIGHT     = "ARM_NIGHT"


def _device_block(cfg):
    return {
        "identifiers":    [DEVICE_ID],
        "name":           cfg.get("alarm_name", "RSI Videofied Alarm"),
        "model":          "Videofied XT",
        "manufacturer":   "RSI Video Technologies",
        "sw_version":     "2.0"
    }


def _slug(name):
    return name.lower().replace(" ", "_")


def mqtt_start_server(cfg, command_callback=None):
    logging.info("MQTT connecting to %s:%s" % (cfg["mqtt_host"], cfg["mqtt_port"]))
    client = mqtt.Client()

    if cfg.get("mqtt_user") and cfg.get("mqtt_pwd"):
        logging.info("MQTT: using username/password")
        client.username_pw_set(cfg["mqtt_user"], cfg["mqtt_pwd"])

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            logging.info("MQTT connected")
            c.subscribe(ALARM_COMMAND_TOPIC)
            logging.info("Subscribed to %s" % ALARM_COMMAND_TOPIC)
        else:
            logging.error("MQTT connection failed (rc=%d)" % rc)

    def on_message(c, userdata, msg):
        cmd = msg.payload.decode().strip().upper()
        logging.info("MQTT command [%s]: %s" % (msg.topic, cmd))
        if command_callback:
            command_callback(cmd)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(cfg["mqtt_host"], cfg["mqtt_port"])
    client.loop_start()
    return client


def mqtt_publish_alarm_state(client, cfg, state):
    logging.info("Alarm state → %s" % state)
    client.publish(ALARM_STATE_TOPIC, state, qos=1, retain=True)


def mqtt_ha_discovery(client, cfg):
    device = _device_block(cfg)

    _publish_discovery(client, "alarm_control_panel", "alarm", json.dumps({
        "name":               cfg.get("alarm_name", "RSI Videofied Alarm"),
        "unique_id":          "%s_alarm" % DEVICE_ID,
        "state_topic":        ALARM_STATE_TOPIC,
        "command_topic":      ALARM_COMMAND_TOPIC,
        "payload_disarm":     HA_CMD_DISARM,
        "payload_arm_away":   HA_CMD_ARM_AWAY,
        "payload_arm_home":   HA_CMD_ARM_HOME,
        "payload_arm_night":  HA_CMD_ARM_NIGHT,
        "state_disarmed":     HA_STATE_DISARMED,
        "state_armed_away":   HA_STATE_ARMED_AWAY,
        "state_armed_home":   HA_STATE_ARMED_HOME,
        "state_armed_night":  HA_STATE_ARMED_NIGHT,
        "state_triggered":    HA_STATE_TRIGGERED,
        "state_pending":      HA_STATE_PENDING,
        "code":               str(cfg.get("alarm_code", "1234")),
        "code_arm_required":  True,
        "code_disarm_required": True,
        "device":             device
    }))
    logging.info("Discovery sent: alarm_control_panel")

    for sensor_name, v in cfg.get("home_assistant_sensors", {}).items():
        sensor_type  = v["sensor_type"]
        device_class = v.get("device_class")
        state_topic  = "rsi_alarm/%s/%s/state" % (sensor_type, _slug(sensor_name))
        unique_id    = "%s_%s" % (DEVICE_ID, _slug(sensor_name))

        payload = {
            "name":         sensor_name,
            "unique_id":    unique_id,
            "state_topic":  state_topic,
            "device":       device
        }
        if device_class and device_class != "None":
            payload["device_class"] = device_class

        _publish_discovery(client, sensor_type, _slug(sensor_name), json.dumps(payload))

        client.publish(state_topic, v["default_state"], qos=1, retain=True)
        logging.info("Discovery sent: %s/%s (default: %s)" % (sensor_type, sensor_name, v["default_state"]))


def mqtt_publish_sensor(client, cfg, sensor_name, state):
    v = cfg.get("home_assistant_sensors", {}).get(sensor_name)
    if not v:
        logging.warning("Sensor '%s' not found in config" % sensor_name)
        return
    topic = "rsi_alarm/%s/%s/state" % (v["sensor_type"], _slug(sensor_name))
    client.publish(topic, state, qos=1, retain=True)


def _publish_discovery(client, component, object_id, payload_json):
    topic = "homeassistant/%s/%s_%s/config" % (component, DEVICE_ID, object_id)
    client.publish(topic, payload_json, qos=1, retain=True)
    logging.debug("Discovery topic: %s" % topic)


def mqtt_ha_config(client, cfg):
    mqtt_ha_discovery(client, cfg)

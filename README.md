# RSI Videofied tcp / mqtt gateway

This is a simple gateway between RSI Videofied alarm system and MQTT server.
!! I only tested with the RSI protocol V2 !!
It's integrated with [Home Assistant](https://github.com/home-assistant/home-assistant) (automatic creation of sensors through MQTT)

<img width="200" alt="portfolio_view" src="image/../images/RSI_alarm_image.png">

# Alarm configuration
Please, backup actual configuration before any changes !!

## FR (documentations/WIP2x0_InstallationGuide_FR.pdf)
- 4. PARAMETRES ETHRENET (P21)
- 5. CODES ALARME (P22)
-- Tout mettre à "ALARME ET FIN"
- 2. PROGRAMMATION DE LA CENTRALE W (P9)
-- TELESURVEILLANCE
-- ADRESSES SERVEUR -> Docker address
-- PORT --> 888

## EN (documentations/WIP2x0_InstallationGuide_EN.pdf)

# Gateway configuration (config.json)
```json
{
  "socket_bind": "",
  "socket_listen_port": 888,
  "socket_timeout" : 5.0,
  "mqtt_host": "192.168.1.72",
  "mqtt_user": "rsivideofed",
  "mqtt_pwd": "rsivideofed",
  "mqtt_port": 1883,
  "mqtt_prefix": "homeassistant",
  "home_assistant_integration": 1,
  "alarm_code": "12345678",
  "home_assistant_sensors":
  {
    "alarm_arm": { "device_class": "lock", "default_state": "ON", "sensor_type": "binary_sensor" },
    "alarm_arm_source": { "device_class": "None", "default_state": "nobody", "sensor_type": "sensor" },
    "alarm_power": { "device_class": "plug", "default_state": "ON", "sensor_type": "binary_sensor" },
    "alarm_autoprotection": { "device_class": "safety", "default_state": "OFF", "sensor_type": "binary_sensor" },
    "alarm_autoprotection_source": { "device_class": "None", "default_state": "nothing", "sensor_type": "sensor" },
    "alarm_alert": { "device_class": "problem", "default_state": "OFF", "sensor_type": "binary_sensor" },
    "alarm_alert_source": { "device_class": "None", "default_state": "nothing", "sensor_type": "sensor" },
    "alarm_ping": { "device_class": "None", "default_state": "ping", "sensor_type": "sensor" }
  },
  "mapping_events":
  {
    "1": { "type": "alarm_alert", "state": "ON", "comment": "alarm alert !", "device_index": 1  },
    "3": { "type": "alarm_autoprotection", "state": "ON", "comment": "autoprotection !", "device_index": 1  },
    "4": { "type": "alarm_autoprotection", "state": "OFF", "comment": "autoprotection recovery" },
    "5": { "type": "", "state": "OFF", "comment": "Panic Buttons", "device_index": 1},
    "6": { "type": "alarm_5_wrong_codes", "state": "OFF", "comment": "5 wrong codes" },
    "7": { "type": "", "state": "OFF", "comment": "disarmed with duress code +1" },
    "8": { "type": "", "state": "OFF", "comment": "armed with duress code +2" },
    "19": { "type": "alarm_power", "state": "OFF", "comment": "ac power lost" },
    "20": { "type": "alarm_power", "state": "ON", "comment": "ac power recovery" },
    "24": { "type": "alarm_arm", "state": "OFF", "comment": "armed", "mapping_users": 1 },
    "25": { "type": "alarm_arm", "state": "ON", "comment": "disarmed", "mapping_users": 1 },
    "26": { "type": "alarm_ping", "state": "pong", "comment": "ping / pong" },
    "27": { "type": "alarm_alert", "state": "OFF", "comment": "intrusion ack" }
  },
  "mapping_users":
  {
    "1": "Manon",
    "2": "Mickael",
    "3": "Allan",
    "100": "Telecomande"
  },
  "device_index": {
    "1": { "name" : "Clavier", "zone": 1 },
    "2": { "name" : "IR entrance", "zone": 1 },
    "3": { "name" : "Baie Vitree", "zone": 1 },
    "4": { "name" : "Indoor siren", "zone": 1 },
    "5": { "name" : "IR stage 1", "zone": 3 },
    "6": { "name" : "Outdoor siren", "zone": 1 },
    "62": { "name" : "Panel", "zone": 2 }
  },
  "zones": {
    "1": { "name" : "Interieur"}
  }
}
```

# My events list (have to change with your own system)
You have to test your own system with arm / disarm / open panel etc .. to find the corrects IDs, please start container in DEBUG mode.
FYI: I haven't all events yet

| Events ID | Events | Remarks |
|--|--|--|
|EVENT,1,2,1|Intrusions detected|1 = Events ID / 2 = Device Index / 1 = Detector Index|
|EVENT,3,62,0|autoprotection start|3 = Events ID / 62 = Device Index / 0 = ??? |
|EVENT,4|autoprotection end|4 = Events ID |
|EVENT,5,1,0|panic buttons|5 = Events ID / 1 = ?? / 0 = ?? |
|EVENT,6|5 wrong codes|6 = Events ID |
|EVENT,7,1,3|disarmed with duress code +1|7 = Events ID / 1 = ?? / 3 = ??|
|EVENT,8,1,3|armed with duress code +2|8 = Events ID / 1 = ?? / 3 = ??|
|EVENT,15|Battery low level|15 = Events ID |
|EVENT,16|After event 15, Battery OK|16 = Events ID |
|EVENT,19|AC power loss|19 = Events ID |
|EVENT,20|AC power recovery|20 = Events ID |
|EVENT,24,1,3|Armed|24 = Events ID / 1 = ?? / 3 = user ID |
|EVENT,25,0,3|Disarmed|25 = Events ID / 0 = ?? / 3 = user ID |
|EVENT,26|cyclic test|26 = Events ID|
|EVENT,27|After disarm confirmation of intrusion detected|27 = Events ID |

# Panel tested firmwares
- 07.03.19.03859C
- 09.01.49.0203809

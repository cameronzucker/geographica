from collections import defaultdict
from skidl import Pin, Part, Alias, SchLib, SKIDL, TEMPLATE

from skidl.pin import pin_types

SKIDL_lib_version = '0.0.1'

circuit = SchLib(tool=SKIDL).add_parts(*[
        Part(**{ 'name':'Conn_01x06', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'Conn_01x06'}), 'ref_prefix':'J', 'fplist':[''], 'footprint':'Connector_JST:JST_SH_BM06B-SRSS-TB_1x06-1MP_P1.00mm_Vertical', 'keywords':'connector', 'description':'Generic connector, single row, 01x06, script generated (kicad-library-utils/schlib/autogen/connector/)', 'datasheet':'~', 'pins':[
            Pin(num='1',name='Pin_1',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',name='Pin_2',func=pin_types.PASSIVE,unit=1),
            Pin(num='3',name='Pin_3',func=pin_types.PASSIVE,unit=1),
            Pin(num='4',name='Pin_4',func=pin_types.PASSIVE,unit=1),
            Pin(num='5',name='Pin_5',func=pin_types.PASSIVE,unit=1),
            Pin(num='6',name='Pin_6',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'MCP23017_SO', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'MCP23017_SO'}), 'ref_prefix':'U', 'fplist':['Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm'], 'footprint':'Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm', 'keywords':'I2C parallel port expander', 'description':'16-bit I/O expander, I2C, interrupts, w pull-ups, GPA/B7 output only (https://microchip.my.site.com/s/article/GPA7---GPB7-Cannot-Be-Used-as-Inputs-In-MCP23017),  SOIC-28', 'datasheet':'https://ww1.microchip.com/downloads/aemDocuments/documents/APID/ProductDocuments/DataSheets/MCP23017-Data-Sheet-DS20001952.pdf', 'pins':[
            Pin(num='13',name='SDA',func=pin_types.BIDIR,unit=1),
            Pin(num='12',name='SCK',func=pin_types.INPUT,unit=1),
            Pin(num='19',name='INTB',func=pin_types.TRISTATE,unit=1),
            Pin(num='20',name='INTA',func=pin_types.TRISTATE,unit=1),
            Pin(num='18',name='~{RESET}',func=pin_types.INPUT,unit=1),
            Pin(num='17',name='A2',func=pin_types.INPUT,unit=1),
            Pin(num='16',name='A1',func=pin_types.INPUT,unit=1),
            Pin(num='15',name='A0',func=pin_types.INPUT,unit=1),
            Pin(num='11',name='NC',func=pin_types.NOCONNECT,unit=1),
            Pin(num='14',name='NC',func=pin_types.NOCONNECT,unit=1),
            Pin(num='9',name='VDD',func=pin_types.PWRIN,unit=1),
            Pin(num='10',name='VSS',func=pin_types.PWRIN,unit=1),
            Pin(num='1',name='GPB0',func=pin_types.BIDIR,unit=1),
            Pin(num='2',name='GPB1',func=pin_types.BIDIR,unit=1),
            Pin(num='3',name='GPB2',func=pin_types.BIDIR,unit=1),
            Pin(num='4',name='GPB3',func=pin_types.BIDIR,unit=1),
            Pin(num='5',name='GPB4',func=pin_types.BIDIR,unit=1),
            Pin(num='6',name='GPB5',func=pin_types.BIDIR,unit=1),
            Pin(num='7',name='GPB6',func=pin_types.BIDIR,unit=1),
            Pin(num='8',name='GPB7',func=pin_types.OUTPUT,unit=1),
            Pin(num='21',name='GPA0',func=pin_types.BIDIR,unit=1),
            Pin(num='22',name='GPA1',func=pin_types.BIDIR,unit=1),
            Pin(num='23',name='GPA2',func=pin_types.BIDIR,unit=1),
            Pin(num='24',name='GPA3',func=pin_types.BIDIR,unit=1),
            Pin(num='25',name='GPA4',func=pin_types.BIDIR,unit=1),
            Pin(num='26',name='GPA5',func=pin_types.BIDIR,unit=1),
            Pin(num='27',name='GPA6',func=pin_types.BIDIR,unit=1),
            Pin(num='28',name='GPA7',func=pin_types.OUTPUT,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'C', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C'}), 'ref_prefix':'C', 'fplist':[''], 'footprint':'Capacitor_SMD:C_0603_1608Metric', 'keywords':'cap capacitor', 'description':'Unpolarized capacitor', 'datasheet':'~', 'pins':[
            Pin(num='1',name='~',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',name='~',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'R', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R'}), 'ref_prefix':'R', 'fplist':[''], 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':'R res resistor', 'description':'Resistor', 'datasheet':'~', 'pins':[
            Pin(num='1',name='~',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',name='~',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'SW_Push', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'SW_Push'}), 'ref_prefix':'SW', 'fplist':[''], 'footprint':'Button_Switch_SMD:SW_SPST_B3S-1000', 'keywords':'switch normally-open pushbutton push-button', 'description':'Push button switch, generic, two pins', 'datasheet':'~', 'pins':[
            Pin(num='1',name='1',func=pin_types.PASSIVE),
            Pin(num='2',name='2',func=pin_types.PASSIVE)], 'unit_defs':[] }),
        Part(**{ 'name':'LED', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'LED'}), 'ref_prefix':'D', 'fplist':[''], 'footprint':'LED_SMD:LED_0603_1608Metric', 'keywords':'LED diode', 'description':'Light emitting diode', 'datasheet':'~', 'pins':[
            Pin(num='1',name='K',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',name='A',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'MountingHole', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'MountingHole'}), 'ref_prefix':'H', 'fplist':[''], 'footprint':'MountingHole:MountingHole_2.7mm_M2.5', 'keywords':'mounting hole', 'description':'Mounting Hole without connection', 'datasheet':'~' })])
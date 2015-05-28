import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from _elementtree import ElementTree

class VIFXmlConfig(object):
    def __init__(self, name, mac, ip, vlan, driver, bridge):
        self.name = name
        self.mac = mac
        self.ip = ip
        self.vlan = vlan
        self.driver = driver
        self.bridge = bridge
    def netXmlConfig(self):
        
        root = ET.Element("network")
        name = ET.SubElement(root, "name")
        name.text = self.name
        forward = ET.SubElement(root, "forward")
        forward.set("mode", 'nat')
        bridge = ET.SubElement(root, "bridge")
        bridge.set("name", self.bridge)
        ip = ET.SubElement(root, "ip")
        ip.set("address",self.ip['address'])
        ip.set("netmask", self.ip['netmask'])
        dhcp = ET.SubElement(ip, "dhcp")
        range = ET.SubElement(dhcp, "range")
        range.set("start", self.ip['start'])
        range.set("end", self.ip['end'])
        net_xml = ET.tostring(root, 'utf-8')
        return net_xml
    
    def vifXmlConfig(self):
        root = ET.Element('interface')
        root.set('type', 'bridge')
        if not self.mac == None:
            mac = ET.SubElement(root, "mac")
            mac.set("address", self.mac) 
        source = ET.SubElement(root, 'source')
        source.set('bridge', self.bridge)
        model = ET.SubElement('type',self.driver)
        vif_xml = ET.tostring(root, 'utf-8')
        return vif_xml
            
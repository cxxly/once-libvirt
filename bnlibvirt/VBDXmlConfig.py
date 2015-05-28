import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from _elementtree import ElementTree

class VBDXmlConfig(object):
    def __init__(self, file, driver, phy):
        self.file = file
        self.driver = driver
        self.phy = phy
    def vbdXmlConfig(self):
        
        root = ET.Element("disk")
        root.set('device', 'disk')
        root.set('type','file')
        
        source = ET.SubElement(root, 'source')
        source.set('file', self.file)
        
        backingStore = ET.SubElement(root, 'backingStore')
        target = ET.SubElement(root, 'target')
        target.set('bus', 'xen')
        target.set('dev', self.phy)
        
        vbd_xml = ET.tostring(root, 'utf-8')
        
        writefile = open(self.file[0:-4]+'.xml','w')
        writefile.writelines(vbd_xml)
        writefile.close()
        

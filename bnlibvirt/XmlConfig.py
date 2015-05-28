import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from _elementtree import ElementTree

class XmlConfig(object):
    def __init__(self, domid, name, memory, vcpu, image, tap2, vif, vbd, vfb, console):
        self.domid = domid
        self.name = name
        self.memory = memory
        self.vcpu = vcpu
        self.image = image
        self.tap2 = tap2
        self.vif = vif
        self.vbd = vbd
        self.vfb = vfb
        self.console = console
    def xmlConfig(self):
        
        root = ET.Element("domain")
        root.set("id", self.domid)
        root.set("type", 'xen')
        
        name = ET.SubElement(root, "name")
        name.text = self.name
        
        memory = ET.SubElement(root, "memory")
        memory.text = str(int(self.memory)*1024)
#         memory.text = '1000'
        memory.set("unit", 'KiB')
        
        currentmemory = ET.SubElement(root, "currentmemory")
        currentmemory.text = str(int(self.memory)*1024)
#         currentmemory.text = '1000'
        currentmemory.set("unit", 'KiB')
        
        vcpu = ET.SubElement(root, "vcpu")
        vcpu.text = self.vcpu
        vcpu.set("placement", 'static')
        
        os = ET.SubElement(root,"os")
        
        features = ET.SubElement(root,"features")
        acpi = ET.SubElement(features,"acpi")
        apic = ET.SubElement(features,"apic")
        pae = ET.SubElement(features,"pae")
        
        clock = ET.SubElement(root,"clock")
        clock.set("offset",'utc')
        
        on_power = ET.SubElement(root,"on_power")
        on_power.text = "destroy"
        on_reboot = ET.SubElement(root,"on_reboot")
        on_reboot.text = "destroy"       
        on_crash = ET.SubElement(root,"on_crash")
        on_crash.text = "destroy"
        
        device = ['cdrom','hd']
        for key in self.image:
            type = ET.SubElement(os, "type")
            type.text = key
            type.set("arch", 'x86_64')
            type.set("machine", 'xenfy')
        
            loader = ET.SubElement(os, "loader")
            loader.text = self.image[key]['loader']
            loader.set("type", 'rom')
        
            boot = ET.SubElement(os,"boot")
            boot.set("dev",self.image[key]['boot'])
            
            device.remove(self.image[key]['boot'])
            for element in device:
                boot = ET.SubElement(os,"boot")
                boot.set("dev",str(element))
            
            devices = ET.SubElement(root,"devices")
            emulator = ET.SubElement(devices,"emulator")
            emulator.text = self.image[key]['device_model']
        
        disk = ET.SubElement(devices, "disk")
        disk.set("type","file")
        disk.set("device",self.vbd['dev'][4:])
        source = ET.SubElement(disk,"source")
        source.set("file",self.vbd['uname'][8:])
        backingStore = ET.SubElement(disk,"backingStore")
        target = ET.SubElement(disk,"target")
        target.set("dev",self.vbd['dev'][0:3])
        target.set("bus",'virtio')
        if self.vbd['mode'] == 'r':
            readonly = ET.SubElement(disk, "readonly")
        address = ET.SubElement(disk,"address")
        address.set("type","drive")
        address.set("controller",'0')
        address.set("bus",'1')
        address.set("target",'0')
        address.set("unit",'0')        
        
        disk = ET.SubElement(devices, "disk")
        disk.set("type","file")
        disk.set("device",self.tap2['dev'][4:])
        source = ET.SubElement(disk,"source")
        source.set("file",self.tap2['uname'][8:])
        backingStore = ET.SubElement(disk,"backingStore")
        target = ET.SubElement(disk,"target")
        target.set("dev",self.tap2['dev'][0:3])
        target.set("bus",'virtio')
        if self.tap2['mode'] == 'r':
            readonly = ET.SubElement(disk, "readonly")
        address = ET.SubElement(disk,"address")
        address.set("type","drive")
        address.set("controller",'0')
        address.set("bus",'1')
        address.set("target",'0')
        address.set("unit",'0')    
            
        controller = ET.SubElement(devices,"controller")
        controller.set("type",'usb')
        controller.set("index",'0')
        controller.set("model",'ich9-ehci1')
        for i in range(0,1):
            controller = ET.SubElement(devices,"controller")
            controller.set("type",'usb')
            controller.set("index",'0')
            controller.set("model",'ich9-ehci'+str(i+1))
            master = ET.SubElement(controller,"master")
            master.set("startport",str(i*2))
        
        interface = ET.SubElement(devices,"interface")
        interface.set("type",'bridge')
        mac = ET.SubElement(interface,"mac")
        mac.set("address",self.vif['mac'])
        source = ET.SubElement(interface,"source")
        source.set("bridge",self.vif['bridge'])
        
        serial = ET.SubElement(devices,"serial")
        serial.set("type",'pty')
        target = ET.SubElement(serial,"target")
        target.set("port",'0')
        
        console = ET.SubElement(devices,"console")
        console.set("type",'pty')
        target = ET.SubElement(console,"target")
        target.set("type",'serial')
        target.set("port",self.console['location'])
        
        input = ET.SubElement(devices,"input")
        input.set("type","tablet")
        input.set("bus","usb")
        
        graphics = ET.SubElement(devices, "graphics")
        graphics.set("type", 'vnc')
        graphics.set("port", self.vfb['location'][8:])
        graphics.set("autoport", 'yes')
        graphics.set("listen", self.vfb['location'][0:7])
        listen = ET.SubElement(graphics,"listen")
        listen.set("type","address")
        listen.set("address",self.vfb['vnclisten'])
        
        video = ET.SubElement(devices,"video")
        model = ET.SubElement(video,"model")
        model.set("type","vga")
        model.set("vram","8192")
        model.set("heads",'1')
        rough_string = ET.tostring(root, 'utf-8')
#         reparsed = minidom.parseString(rough_string)
#         xml_config = reparsed.toprettyxml(indent=" " , encoding="utf-8")
        
        return rough_string
        
#         file = open("/home/test/"+self.name+".xml",'w')
#         file.writelines(rough_string)
#         file.close()
#          
#         return "/home/test/"+self.name+".xml"
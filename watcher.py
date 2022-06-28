import argparse
import os
import sys

import docker

def parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='')
    parser.add_argument('--template-path', default='/etc/nginx/conf.d.template')
    parser.add_argument('--destination-path', default='/etc/nginx/conf.d')
    return parser.parse_args(args)



def get_currently_running_web_servers(client, args):
    filters = {'status': 'running'}
    if args.label:
        filters['label'] = args.label
    web_containers = client.containers.list(filters=filters)
    result = {}
    for c in web_containers:
        networks = c.attrs['NetworkSettings']['Networks']
        ip = None
        for idx in networks:
            network = networks[idx]
            if 'IPAddress' in network:
                if network['IPAddress'] != None and network['IPAddress'] != "":
                    ip = network['IPAddress']
        result[c.name] = ip
    return result




import os
class ConfTemplateLoader:
    def __init__(self,src_dir="",dest_dir=""):
        """conf template loader"""
        if src_dir=="" or dest_dir ==""or src_dir is None or dest_dir is None :
            raise Exception("Folder not found. please set --template-path and --destination-path correctly.")
        if not (os.path.isdir(src_dir)):
            raise Exception("Source folder "+ src_dir +" not found. please set --template-path and --destination-path correctly.")
        if not ( os.path.isdir(dest_dir)):
            raise Exception("Destination Folder "+ dest_dir +" not found. please set --template-path and --destination-path correctly.")


        self.src_dir = src_dir
        self.dest_dir = dest_dir
        self.templates = {}
        self.refresh()

    def refresh(self):
        """refresh list"""
        src_filelist = []
        dest_filelist = []
        for root, dirs, files in os.walk(self.src_dir):
            for file in files:
                if not file.endswith((".swp","~","swx")):
                    src_filelist.append(  os.path.join(root,file)  );
                    dest_filelist.append( os.path.join(root.replace(self.src_dir,self.dest_dir),file) );

        self.templates = {}
        for idx,filetmpl in enumerate(src_filelist):
            template = ConfTemplate(src_filelist[idx],dest_filelist[idx])
            for upstream in template.listupstream:
                self.templates[upstream] = template

    def get_all(self):
        """get list object ConfTemplate"""
        self.refresh()
        return self.templates

    def search(self, name):
        """get template"""
        return {name:self.templates[name]} if name in self.templates else []


import re
class ConfTemplate:
    def __init__(self,src_file,dest_file):
        """Get info conf & template"""
        self.src_file = src_file
        self.dest_file = dest_file
        self.dest_dir = os.path.dirname(dest_file)

        template  = self.get_content(src_file)
        rendered  = self.get_content(dest_file)
        self.template = template
        self.rendered = rendered
        self.old_rendered = rendered

        self.is_draft = 0

        self.listupstream = self.parse_upstream(template)

    def get_content(self,fileread):
        """read content file"""
        if not os.path.isfile(fileread):
            return None

        data = None
        with open(fileread, 'r') as file:
            data = file.read()
        return data

    def parse_upstream(self,x):
        """parse list upstream from template"""
        return re.findall(r"^.*?upstream.*?server\s.*?(\S.*?)_IP",x,re.MULTILINE)

    def render_ip(self,hostname,ip):
        """render new config from template"""
        if self.is_draft == 0:
            self.is_draft = 1
            self.rendered = self.template.replace(hostname+"_IP",ip)
        else:
            self.rendered = self.rendered.replace(hostname+"_IP",ip)

    def persist(self):
        """Update nginx conf in dest folder"""
        if not os.path.isdir(self.dest_dir):
            os.makedir(self.dest_dir, exist_ok=True)

        if self.rendered == None:
            if os.path.isfile(self.dest_file):
                os.remove(self.dest_file)
        else:
            with open(self.dest_file, 'w') as file:
                file.write(self.rendered)


    def commit(self):
        """commit changes"""
        self.old_rendered = self.rendered
        self.is_draft = 0

    def rollback(self):
        """rollback to prev"""
        self.rendered = self.old_rendered
        self.is_draft = 0
        self.persist()



import subprocess
def check(ret):
    if ret != 0:
        if ret < 0:
            raise Exception("Killed by signal {}".format(ret))
        else:
            raise Exception("Command failed with return code {}".format(ret))
def nginx_reload():
    ret = subprocess.call('nginx -t', shell=True)
    check(ret)
    ret = subprocess.call('nginx -s reload', shell=True)
    check(ret)


def render_all_template(templates,webservers):
    print(templates)
    for template in templates:

        a = 0
        b = 0
        for upstream in templates[template].listupstream:
            a = a + 1
            if template in webservers:
                b = b + 1
                hostname = upstream
                ip = webservers[hostname]
                templates[template].render_ip(hostname,ip)

        if a!=b:
            templates[template].rendered = None

        templates[template].persist()

    nginx_reload()
    for template in templates:
        templates[template].commit()

def rollback_all_template(templates,webservers):
    for template in templates:
        templates[template].rollback()
    nginx_reload()


def listen_for_events(client, args, loader, containers):
    event_filters = {'type': 'container'}
    if args.label:
        filters['label'] = args.label
    for event in client.events(filters=event_filters, decode=True):
        status   = event['status']
        if status not in ['start','stop','die']:
            continue

        #hostname = event['id']
        hostname = event['Actor']['Attributes']['name']
        if status == 'start':
            container = client.containers.get(event['id'])
            print(container.attrs)
            networks = container.attrs['NetworkSettings']['Networks']
            ip = None
            for idx in networks:
                network = networks[idx]
                if 'IPAddress' in network:
                    if network['IPAddress'] != None and network['IPAddress'] != "":
                        ip = network['IPAddress']
            containers[hostname] = ip
        elif status in ['stop','die']:
            if hostname in containers:
                del containers[hostname]

        templates = loader.search(hostname)
        try:
            render_all_template(templates,containers)
        except Exception as e:
            rollback_all_template(templates,containers)

        print("Detected container {} with {} status".format(hostname, status))


from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ConfDWatcher(FileSystemEventHandler):
    def __init__(self,src_dir="",dest_dir=""):
        """conf template loader"""
        if src_dir=="" or dest_dir ==""or src_dir is None or dest_dir is None :
            raise Exception("Folder not found. please set --template-path and --destination-path correctly.")
        if not (os.path.isdir(src_dir)):
            raise Exception("Source folder "+ src_dir +" not found. please set --template-path and --destination-path correctly.")
        if not ( os.path.isdir(dest_dir)):
            raise Exception("Destination Folder "+ dest_dir +" not found. please set --template-path and --destination-path correctly.")


        self.src_dir = src_dir
        self.dest_dir = dest_dir
        self.files = {}
        self.templates = {}
        self.observer = Observer()
        self.observer.schedule(self, self.dest_dir, recursive=True)
        self.refresh()

    def refresh(self):
        for root, dirs, files in os.walk(self.src_dir):
            for file in files:
                filename = os.path.join(root.replace(self.src_dir,""),file)
                if not file.endswith((".swp","~","swx")):
                    self.templates[filename] = {
                        "file": os.path.join(root,file),
                        "dir": root,
                    }

        for root, dirs, files in os.walk(self.dest_dir):
            for file in files:
                filename = os.path.join(root.replace(self.dest_dir,""),file)
                if(filename in self.templates and not filename.endswith((".swp","~","swx")) ):
                    self.files[filename] = {
                        "file": os.path.join(root,file),
                        "dir": root,
                    }

    def update_template(self,file_changed):
        print("update_template :" +file_changed)
        return True

    def is_watched(self,file_changed):
        for filename in self.files:
            if file_changed == self.files[filename]["file"]:
                return True
        return False

    def on_modified(self, event):
        if not event.is_directory and self.is_watched(event.src_path):
            self.update_template(event.src_path)

    def watch(self):
        self.observer.start()
        self.observer.join()

class ConfDTemplateWatcher(FileSystemEventHandler):
    def __init__(self,loader: ConfTemplateLoader, containers):
        self.loader = loader
        self.containers = containers
        self.observer = Observer()
        self.observer.schedule(self, self.loader.src_dir, recursive=True)

    def on_any_event(self, event):
        if not event.is_directory and not event.src_path.endswith((".swp","~","swx")):
            print(event.src_path)
            templates = self.loader.get_all()
            try:
                render_all_template(templates,self.containers)
            except Exception as e:
                rollback_all_template(templates,self.containers)

    def watch(self):
        self.observer.start()
        self.observer.join()


def watch_docker(client, args, loader, containers):
    print("watch_docker")
    #await asyncio.sleep(0.01)

    #await asyncio.sleep(0.01)
    listen_for_events(client, args, loader, containers)
    print("watch_docker DONE")

def watch_conf_d(template_path,destination_path):
    print("watch_conf_d")
    #await asyncio.sleep(0.01)

    confd = ConfDWatcher(template_path,destination_path)
    confd.watch()
    print("watch_conf_d DONE")


def watch_conf_d_template(loader,containers):
    print("watch_conf_d_template")
    #await asyncio.sleep(0.01)

    confd = ConfDTemplateWatcher(loader,containers)
    confd.watch()
    print("watch_conf_d_template DONE")


from concurrent.futures import ThreadPoolExecutor, as_completed

def main(args):

    args = parse_args(args)
    client = docker.from_env()
    containers = get_currently_running_web_servers(client, args)

    loader = ConfTemplateLoader(args.template_path,args.destination_path)
    templates = loader.get_all()
    #templates = loader.search("addon_indoormaps_nginx")
    #print(containers)
    try:
        render_all_template(templates,containers)
    except Exception as e:
        rollback_all_template(templates,containers)


    #loop = asyncio.get_event_loop()

    #tasks = [
    #    watch_conf_d_template(loader,containers)
        #,watch_conf_d_template(loader,containers)
    #    ,watch_docker(client, args, loader, containers)
    #]

    #commands = asyncio.gather(*tasks
        #watch_conf_d(args.template_path,args.destination_path)
        #watch_conf_d_template(loader,containers)
    #)
    #result = loop.run_until_complete(commands)
    #result = watch_conf_d_template(sys.argv[1:])

    #print(result)
    #loop.close()

    with ThreadPoolExecutor() as executor:
        futures=[]
        futures.append(executor.submit(watch_conf_d_template,loader,containers))
        futures.append(executor.submit(watch_docker,client, args, loader, containers))
        for future in as_completed(futures):
            print(future.result())


if __name__ == '__main__':
    main(sys.argv[1:])

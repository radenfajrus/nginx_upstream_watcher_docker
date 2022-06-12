import argparse
import os
import sys

import docker

def parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--nginx-label', default='')
    parser.add_argument('--web-label', default='')
    #parser.add_argument('--network', default='envisions')
    parser.add_argument('--template-path', default='/etc/nginx/conf.d.template')
    parser.add_argument('--destination-path', default='/etc/nginx/conf.d')
    parser.add_argument('--web-port', type=int, default=5090)
    return parser.parse_args(args)



def get_currently_running_web_servers(client, args):
    filters = {'status': 'running'}
    if args.web_label:
        filters['label'] = args.web_label
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


def listen_for_events(client, args, web_servers):
    event_filters = {'type': 'container', 'label': args.web_label}
    for event in client.events(filters=event_filters, decode=True):
        print(event)
        if event['status'] == 'start':
            web_servers[event['id']] = client.containers.get(event['id'])
        elif event['status'] == 'stop':
            del web_servers[event['id']]
        else:
            continue
        print("Detected container {} with {} status".format(event['id'], event['status']))
        reload_nginx(client, web_servers, args)




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
                src_filelist.append(  os.path.join(root,file)  );
                dest_filelist.append( os.path.join(root.replace(self.src_dir,self.dest_dir),file) );

        self.templates = {}
        for idx,filetmpl in enumerate(src_filelist):
            template = ConfTemplate(src_filelist[idx],dest_filelist[idx])
            for upstream in template.listupstream:
                self.templates[upstream] = template

    def get_all(self):
        """get list object ConfTemplate"""
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
    for template in templates:
        #print(template)

        a = 0
        b = 0
        for upstream in templates[template].listupstream:
            a = a + 1
            if template in webservers:
                b = b + 1
                hostname = upstream
                ip = webservers[template]
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


def main(args):
    args = parse_args(args)
    client = docker.from_env()
    containers = get_currently_running_web_servers(client, args)

    loader = ConfTemplateLoader(args.template_path,args.destination_path)
    #templates = loader.get_all()
    templates = loader.search("addon_indoormaps_nginx")

    try:
        render_all_template(templates,containers)
    except Exception as e:
        rollback_all_template(templates,containers)



if __name__ == '__main__':
    main(sys.argv[1:])

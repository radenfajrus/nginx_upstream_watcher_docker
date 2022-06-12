# nginx_upstream_watcher_docker

Using docker for managing multiple services was a good choice, especially when your client needs on premise deployment.

The problem is how to manage port from multiple container.
Let say, 2 team develop nodejs app with default port 3000.
You cant just docker run these 2 docker because of port conflict.
Allocating port manually was breaking docker purpose for being "easy" and "safe" deployment.
Using kubernetes was out of option, because of complexity on cloud and on-premise deployment.

Inspired from https://www.ameyalokare.com/docker/2017/09/27/nginx-dynamic-upstreams-docker.html, 
you can solve that by access directly to docker network ip.

Few solution that not working:
1. dns-proxy-server could provide dns resolver to nginx. But, changing ip container not being reflected to nginx resolver.
https://stackoverflow.com/questions/67439712/nginx-does-not-re-resolve-dns-names-in-docker
2. nginx-proxy-manager could directly access to container using container name by running it on same docker network.
But, deleting container potentially cause upstream failed that shutdown whole system.
https://github.com/NginxProxyManager/nginx-proxy-manager/issues/633
3. Traefik doesnt support php cgi for some laravel and wordpress services.
https://github.com/traefik/traefik/issues/753

Using template based nginx config give more freedom to add more feature, like Dynamic Canary Deployment or Dynamic Tenant Subdomain.



<br><hr>
pip3 install docker  
python3 watcher.py  

Argument:  
- --label (default='')
- --template-path (default='/etc/nginx/conf.d.template')
- --destination-path (default='/etc/nginx/conf.d')



cp nginx-docker-watcher.service /usr/lib/systemd/system/nginx-docker-watcher.service  
systemctl daemon-reload  
systemctl enable nginx-docker-watcher  
systemctl start nginx-docker-watcher   
systemctl status nginx-docker-watcher  


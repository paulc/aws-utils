#!/usr/bin/env python3

import boto3
import click
import os,subprocess,sys,time

from botocore.exceptions import ClientError
from tabulate import tabulate

def getpath(val,path):
    if '.' in path:
        head,tail = path.split('.',2)
        return getpath(val[head],tail)
    else:
        return val[path]

def extract(val,*attrs):
    i = {}
    for a in attrs:
        name,path = a.split(':',2) if ':' in a else (a,a)
        i[name] = getpath(val,path)
    return i

def check_key(key):
    cmd = """ssh-keygen -y -f "{key}" </dev/null >/dev/null 2>&1 || 
                    ssh-add -l | grep -q "{key}" ||
                    ssh-add {key}""".format(key=key)
    subprocess.run(cmd,shell=True)

@click.group()
def cli():
    pass

@cli.command()
@click.option('--name',default=None,help='Instance name')
@click.option('--params',default=None,help='Instance parameters')
def ls(name,params):
    params = params or '''
        name
        state:state.name
        zone:location.availabilityZone
        ip:publicIpAddress
        blueprint:blueprintId
        user:username
        key:sshKeyName
    '''
    params = params.split() 
    lightsail = boto3.client('lightsail')
    if name:
        try:
            instance = lightsail.get_instance(instanceName=name)['instance']
            click.echo(tabulate([extract(instance,*params)],headers='keys'))
        except ClientError as e:
            click.echo(e)
    else:
        try:
            instances = lightsail.get_instances()['instances']
            click.echo(tabulate([extract(x,*params) for x in instances],headers='keys'))
        except ClientError as e:
            click.echo(e)

@cli.command()
@click.option('--params',default=None,help='Display parameters')
def blueprints(params):
    params = params or '''
        id:blueprintId
        name
    '''
    params = params.split()
    lightsail = boto3.client('lightsail')
    try:
        r = lightsail.get_blueprints()['blueprints']
        click.echo(tabulate([extract(x,*params) for x in r],headers='keys'))
    except ClientError as e:
        click.echo(e)

@cli.command()
@click.option('--params',default=None,help='Display parameters')
def bundles(params):
    params = params or '''
        id:bundleId
        cpu:cpuCount
        ram:ramSizeInGb
        disk:diskSizeInGb
        transfer:transferPerMonthInGb
    '''
    params = params.split()
    lightsail = boto3.client('lightsail')
    try:
        r = lightsail.get_bundles()['bundles']
        click.echo(tabulate([extract(x,*params) for x in r],headers='keys'))
    except ClientError as e:
        click.echo(e)

@cli.command()
@click.option('--params',default=None,help='Display parameters')
@click.option('--name',default=None,help='Key name')
@click.option('--new',default=None,help='SSH public key',type=click.File())
@click.option('--delete',default=None,help='Delete key')
def keys(params,new,name,delete):
    params = params or '''
        name
        zone:location.regionName
    '''
    params = params.split()
    lightsail = boto3.client('lightsail')
    if new:
        if not name:
            click.echo("ERROR: Key name required (--name)")
            return
        try:
            r = lightsail.import_key_pair(keyPairName=name,publicKeyBase64=new.read())['operation']
            click.echo(tabulate([extract(r,'name:resourceName','status')],headers='keys')) 
        except ClientError as e:
            click.echo(e)
    elif delete:
        try:
            r = lightsail.delete_key_pair(keyPairName=delete)['operation']
            click.echo(tabulate([extract(r,'name:resourceName','status')],headers='keys')) 
        except ClientError as e:
            click.echo(e)

    else:
        try:
            data = lightsail.get_key_pairs()['keyPairs']
            click.echo(tabulate([extract(x,*params) for x in data],headers='keys'))
        except ClientError as e:
            click.echo(e)

@cli.command()
@click.argument('name',nargs=1,required=True)
@click.argument('cmd',nargs=-1)
def ssh(name,cmd):
    lightsail = boto3.client('lightsail')
    try:
        instance = lightsail.get_instance(instanceName=name)['instance']
    except ClientError as e:
        click.echo(e)
    keypath = '{home}/.ssh/{key}'.format(home=os.getenv('HOME'),key=getpath(instance,'sshKeyName'))
    args = [ 'ssh', 
             '-i', keypath,
             '-l', getpath(instance,'username'),
             getpath(instance,'publicIpAddress') ]
    if cmd:
        args.extend([' '.join(cmd)])
    subprocess.run(args)

@cli.command()
@click.option('--name',required=True,help="Instance name")
@click.option('--cmd',help="Command")
@click.option('--timeout',type=float,default=None,help="Timeout")
@click.option('--pipe',help='Pipe file to stdin',type=click.File())
def cmd(name,cmd,timeout,pipe):
    lightsail = boto3.client('lightsail')
    try:
        instance = lightsail.get_instance(instanceName=name)['instance']
        keypath = '{home}/.ssh/{key}'.format(home=os.getenv('HOME'),key=getpath(instance,'sshKeyName'))
        args = [ 'ssh', 
                 '-i', keypath,
                 '-l', getpath(instance,'username'),
                 '-o', 'StrictHostKeyChecking=no',
                 getpath(instance,'publicIpAddress'),
                 cmd or "uname -a" ]
        try:
            check_key(keypath)
            if pipe:
                result = subprocess.run(args,timeout=timeout,stdin=pipe)
            else:
                result = subprocess.run(args,timeout=timeout)
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired as e:
            sys.exit(1)
    except ClientError as e:
        click.echo(e,err=True)
        sys.exit(1)

@cli.command()
@click.option('--name',help='Instance name(s)',required=True)
@click.option('--zone',help='Availability zone',required=True,envvar="LS_ZONE")
@click.option('--blueprint',help='Blueprint ID',required=True,envvar="LS_BLUEPRINT")
@click.option('--bundle',help='Bundle ID',required=True,envvar="LS_BUNDLE")
@click.option('--key',help='Keypair name',required=True,envvar="LS_KEY")
@click.option('--userdata',help='Userdata',default='')
@click.option('--shell',help='Connect once instance initialised',is_flag=True)
@click.option('--config',help='Exec config file',type=click.File())
def new(name,zone,blueprint,bundle,key,userdata,shell,config):
    lightsail = boto3.client('lightsail')
    try:
        r = lightsail.create_instances(instanceNames=(name,),
                                       availabilityZone=zone,
                                       blueprintId=blueprint,
                                       bundleId=bundle,
                                       keyPairName=key,
                                       userData=userdata)
        if shell or config:
            instance = lightsail.get_instance(instanceName=name)['instance']
            keypath = '{home}/.ssh/{key}'.format(home=os.getenv('HOME'),key=getpath(instance,'sshKeyName'))
            cmd = [ 'ssh', 
                    '-i', keypath,
                    '-l', getpath(instance,'username'),
                    '-o', 'StrictHostKeyChecking=no',
                    getpath(instance,'publicIpAddress'),
                    "uname -a" ]
            n = 0
            check_key(keypath)
            while True:
                click.echo("\rWaiting" + "." * n,nl=False)
                try:
                    result = subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1)
                    if result.returncode == 0:
                        click.echo()
                        click.echo(result.stdout,nl=False)
                        break
                    else:
                        time.sleep(1)
                except subprocess.TimeoutExpired as e:
                    pass
                n += 1
            time.sleep(1)
            if config:
                conf = cmd[:-1] + ["sudo bash -vx"] 
                print(conf)
                result = subprocess.run(conf,stdin=config)
                if result.returncode != 0:
                    sys.exit(result.returncode)
            if shell:
                shell = cmd[:-1]
                result = subprocess.run(shell)
                sys.exit(result.returncode)
        else:
            click.echo(tabulate([extract(x,'name:resourceName','zone:location.availabilityZone','status','id') 
                                    for x in r['operations']],headers='keys'))
    except ClientError as e:
        click.echo(e)

@cli.command()
@click.option('--name',required=True,help='Instance name')
@click.option('--add',help='Add port (from-to/proto)')
@click.option('--rm',help='Remove port (from-to/proto)')
def ports(name,add,rm):
    lightsail = boto3.client('lightsail')
    try:
        if add:
            ports,proto = add.split('/') if '/' in add else (add,'tcp')
            start,end = [ int(x) for x in (ports.split('-') if '-' in ports else (ports,ports)) ]
            r = lightsail.open_instance_public_ports(instanceName = name,
                            portInfo = { 'fromPort':start, 'toPort':end, 'protocol':proto })
            click.echo(tabulate([extract(r['operation'],'name:resourceName','details:operationDetails','status')],
                                    headers='keys')) 
        elif rm:
            ports,proto = rm.split('/') if '/' in rm else (rm,'tcp')
            start,end = [ int(x) for x in (ports.split('-') if '-' in ports else (ports,ports)) ]
            r = lightsail.close_instance_public_ports(instanceName = name,
                            portInfo = { 'fromPort':start, 'toPort':end, 'protocol':proto })
            click.echo(tabulate([extract(r['operation'],'name:resourceName','details:operationDetails','status')],
                                    headers='keys')) 
        else:
            ports = lightsail.get_instance_port_states(instanceName=name)['portStates']
            click.echo(tabulate(ports,headers='keys'))
    except ClientError as e:
        click.echo(e)


@cli.command()
@click.option('--name',required=True,help='Instance name')
@click.option('--force',help='Dont ask for conformation',is_flag=True)
def rm(name,force):
    lightsail = boto3.client('lightsail')
    try:
        i = lightsail.get_instance(instanceName=name)['instance']
        if force:
            ok = True
        else:
            ok = click.confirm("Delete instance: {name} ({ip}/{zone}/{state}) ?".format_map(
                    extract(i,'name','ip:publicIpAddress','zone:location.availabilityZone','state:state.name')))
        if ok:
            r = lightsail.delete_instance(instanceName=name)
            click.echo(tabulate([extract(x,'name:resourceName','zone:location.availabilityZone','status') 
                                        for x in r['operations']],headers='keys'))
    except ClientError as e:
        click.echo(e)


if __name__ == '__main__':
    cli()

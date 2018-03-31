#!/usr/bin/env python3

import os
import re 
import subprocess
import textwrap

import click
import boto3

from pprint import pprint

from tabulate import tabulate

def getpath(data,path):
    if '.' in path:
        head,tail = path.split('.',1)
        r = getpath(data,head)
        if type(r) is range:
            return [ getpath(data[i],tail) for i in r ]
        else:
            return getpath(r,tail)
    elif path == '[]':
        return range(0,len(data))
    elif path[0] == '[':
        return data[int(path[1:-1])]
    else:
        if path.endswith('?'):
            return data.get(path[:-1],"")
        else:
            return data[path]

def extract(data,*args):
    r = {}
    for arg in args:
        try:
            name,maxlen,fs,key = re.match('(.*?)(?:/(\d+))?(?:\[(.*)\])?:(.*)$',arg).groups()
        except AttributeError:
            name,maxlen,fs,key = arg,None,None,arg
        v = getpath(data,key)
        if fs:
            v = fs.join(v)
        if maxlen and len(v) > int(maxlen):
            v = v[:int(maxlen)+3] + "..."
        r[name] = v
    return r

@click.group()
def cli():
    pass

def parse_ip_permission(perms):
    res = []
    for p in perms:
        if 'FromPort' in p:
            fp,tp,proto = p['FromPort'],p['ToPort'],p['IpProtocol']
            iprange = ",".join(['*' if x['CidrIp'] == '0.0.0.0/0' else x['CidrIp'] 
                                        for x in p['IpRanges']])
            ip6range = ",".join([x['CidrIpv6'] for x in p['Ipv6Ranges']])
            ports = "{}".format(fp) if fp==tp else "{}-{}".format(fp,tp)
            res.append("{}/{}:{}".format(proto,iprange,ports))
        else:
            res.append("*:*")
    return res

@cli.command()
@click.option("--filters",multiple=True,help="SG name")
@click.option("--fields",help="Display fields")
def listsg(filters,fields):
    fields = fields.split() if fields else """
        name/30:GroupName
        id:GroupId
        description/40:Description
    """.split()
    ec2 = boto3.client('ec2')
    f = [ dict(Name=n,Values=[v]) for n,v in [ s.split('=') for s in filters] ]
    r = ec2.describe_security_groups(Filters=f)
    rows = []
    for sg in r['SecurityGroups']:
        header = True 
        perm = parse_ip_permission(sg['IpPermissions'])
        if perm:
            for p in perm:
                if header:
                    row = extract(sg,*fields)
                    row['ports'] = p
                    header = False
                else:
                    row = {'ports':p}
                rows.append(row)
        else:
            row = extract(sg,*fields)
    print(tabulate(rows,headers='keys'))

@cli.command()
@click.option("--id","-i",required=True,help="Security Group Id")
@click.option("--add","-a",default=None,help="Add rule")
@click.option("--delete","-d",default=None,help="Delete rule")
@click.option("--udp","-u",is_flag=True,help="UDP (default TCP)")
def editsg(id,add,delete,udp):
    ec2 = boto3.resource('ec2')
    cidr,ports = add.split(':',1) if add else delete.split(':',1)
    cidr = '0.0.0.0/0' if cidr == '*' else cidr
    fp,tp = [ int(x) for x in (ports.split('-',1) if '-' in ports else (ports,ports)) ] 
    sg = ec2.SecurityGroup(id)
    if add:
        sg.authorize_ingress(CidrIp=cidr,FromPort=fp,ToPort=tp,IpProtocol='udp' if udp else 'tcp')
    else:
        sg.revoke_ingress(CidrIp=cidr,FromPort=fp,ToPort=tp,IpProtocol='udp' if udp else 'tcp')

@cli.command()
@click.option("--name","-n",required=True,help="Name")
@click.option("--description","-d",required=True,help="Description")
def newsg(name,description):
    ec2 = boto3.client('ec2')
    r = ec2.create_security_group(GroupName=name,Description=description)
    click.echo(r['GroupId'])

@cli.command()
@click.option("--id","-i",required=True,help="Security Group Id")
def delsg(id):
    ec2 = boto3.client('ec2')
    ec2.delete_security_group(GroupId=id)

@cli.command()
@click.option('--id',required=True,help="Instance Id")
@click.option('--user',default="ec2-user",help="User Id")
@click.argument('cmd',nargs=-1)
def ssh(id,user,cmd):
    ec2 = boto3.resource('ec2')
    instance = ec2.Instance(id=id)
    key = instance.key_name
    ip = instance.public_ip_address
    keypath = '{home}/.ssh/{key}'.format(home=os.getenv('HOME'),key=key)
    args = [ 'ssh', 
             '-i', keypath,
             '-l', user,
             ip ]
    if cmd:
        args.extend([' '.join(cmd)])
    subprocess.run(args)

@cli.command()
@click.option('--id',required=True,help="Instance Id")
@click.option('--start',is_flag=True)
@click.option('--stop',is_flag=True)
@click.option('--terminate',is_flag=True)
def cmd(id,start,stop,terminate):
    ec2 = boto3.resource('ec2')
    instance = ec2.Instance(id=id)
    if start:
        r = instance.start()
    elif stop:
        r = instance.stop()
    elif terminate:
        r = instance.terminate()
    else:
        click.echo("No action specified",err=True)
    pprint(r)

@cli.command()
@click.option("--filters",multiple=True,help="SG name")
@click.option("--fields",help="Display fields")
def ls(filters,fields):
    fields = fields.split() if fields else """
        id:InstanceId
        type:InstanceType
        ip:PublicIpAddress?
        ami:ImageId
        az:Placement.AvailabilityZone
        key:KeyName
        state:State.Name
        security[,]:SecurityGroups.[].GroupId
    """.split()
    ec2 = boto3.client('ec2')
    f = [ dict(Name=n,Values=[v]) for n,v in [ s.split('=') for s in filters] ]
    r = ec2.describe_instances(Filters=f)
    data = []
    for i in getpath(r,'Reservations.[].Instances?.[0]'):
        f = extract(i,*fields)
        data.append(extract(i,*fields))
    print(tabulate(data,headers='keys'))

@cli.command()
@click.option("--ami",required=True,help="AMI Image Id")
@click.option("--key",required=True,help="Keypair Name")
@click.option("--type",default="t2.micro",help="Instance Type")
@click.option('--zone',help='Availability zone')
@click.option("--min",default=1,help="Min Instances")
@click.option("--max",default=1,help="Max Instances")
@click.option("--sg",multiple=True,help="Security Group Ids")
def new(ami,key,type,zone,min,max,sg):
    ec2 = boto3.resource('ec2')
    if zone:
        response = ec2.create_instances(
                ImageId=ami,
                KeyName=key,
                InstanceType=type,
                Placement={'AvailabilityZone':zone},
                MinCount=min,
                MaxCount=max,
                SecurityGroupIds=sg
        )
    else:
        response = ec2.create_instances(
                ImageId=ami,
                KeyName=key,
                InstanceType=type,
                MinCount=min,
                MaxCount=max,
                SecurityGroupIds=sg
        )
    pprint(response)



if __name__ == '__main__':
    cli()

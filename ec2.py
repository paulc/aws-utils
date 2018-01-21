#!/usr/bin/env python3

import re 
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
        name,key = arg.split(':',1) if ':' in arg else (arg,arg)
        if name.endswith(']'):
            m = re.match('(.*)\[(.*)\]$',name)
            name,fs = m.groups()
            r[name] = fs.join(getpath(data,key))
        else:
            r[name] = getpath(data,key)
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
def listsg():
    ec2 = boto3.client('ec2')
    r = ec2.describe_security_groups()
    rows = []
    for sg in r['SecurityGroups']:
        header = True 
        perm = parse_ip_permission(sg['IpPermissions'])
        if perm:
            for p in perm:
                if header:
                    row = extract(sg,'name:GroupName','id:GroupId','description:Description')
                    row['ports'] = p
                    header = False
                else:
                    row = {'ports':p}
                rows.append(row)
        else:
             rows.append(extract(sg,'name:GroupName','id:GroupId','description:Description'))
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
@click.option("--fields",help="Display fields")
def ls(fields):
    fields = fields.split if fields else """
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
    r = ec2.describe_instances()
    data = []
    for i in getpath(r,'Reservations.[].Instances?'):
        f = extract(i,*fields)
        data.append(extract(i,*fields))
    print(tabulate(data,headers='keys'))

if __name__ == '__main__':
    cli()

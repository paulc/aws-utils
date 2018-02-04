#!/usr/bin/env python3

import configparser
import sys

from base64 import encodestring

import click
import requests

@click.command()
@click.option('--description','-d',required=True,help='Gist description')
@click.option('--private','-p',is_flag=True,help='Private gist')
@click.option('--short','-s',is_flag=True,help='Short URL')
@click.option('--name','-n',help='File name (stdin)')
@click.option('--base64','-b',is_flag=True,help='Base64 encode file(s)')
@click.option('--config','-c',type=click.Path(exists=True),help='Account config')
@click.option('--account','-a',help='GitHub account')
@click.option('--token','-t',help='GitHub token')
@click.argument("files",nargs=-1,type=click.File())
def gist(description,files,name,private,short,base64,config,account,token):
    req = { 'description': description,
            'public': not private,
            'files': {}
            }
    readf = (lambda f:encodestring(f.read().encode()).decode()) if base64 else (lambda f:f.read())
    for f in files:
        filename = name if (f.name == '<stdin>' and name) else f.name
        req['files'][filename] = { 'content': readf(f) }
    if config:
        c = configparser.ConfigParser()
        c.read(config)
        account = c['default']['account']
        token = c['gist']['token']
    auth = (account,(token or click.prompt('Token'))) if account else None
    result = requests.post('https://api.github.com/gists',json=req,auth=auth)
    if not result.ok:
        click.echo("ERROR: {} {}".format(result.status_code,result.json()['message']))
        sys.exit(1)
    else:
        api_response = result.json()
        click.echo("HTML URL: {}".format(api_response['html_url']))
        click.echo("API URL: {}".format(api_response['url']))
        for name in api_response['files']:
            click.echo("Raw URL ({}): {}".format(name,api_response['files'][name]['raw_url']))
        if short:
            response = requests.post('https://git.io',files={'url':(None,api_response['raw_url'])})
            if response.ok:
                click.echo("Short URL: {}".format(response.headers['Location']))
            else:
                click.echo("Error creating short URL")
        sys.exit(0)

if __name__ == '__main__':
    gist()



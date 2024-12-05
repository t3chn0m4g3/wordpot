#!/usr/bin/env python

from flask import request, render_template, redirect, url_for, abort
from wordpot import app, pm
from wordpot.helpers import *
from wordpot.logger import LOGGER

TEMPLATE = app.config['THEME'] + '.html'

@app.route('/', methods=['GET', 'POST'])
@app.route('/<filename>.<ext>', methods=['GET', 'POST'])
def commons(filename=None, ext=None):

    # Plugins hook
    for p in pm.hook('commons'):
        p.start(filename=filename, ext=ext, request=request)
        if 'log' in p.outputs:
            LOGGER.info(p.outputs['log'])
        if 'log_json' in p.outputs:
            if app.config['HPFEEDS_ENABLED']:
                app.config['hpfeeds_client'].publish(app.config['HPFEEDS_TOPIC'], p.outputs['log_json'])
            # Log JSON data to file regardless of HPFEEDS being enabled
            LOGGER.info('%s', p.outputs['log_json'])
        if 'template' in p.outputs:
            
            if 'template_vars' in p.outputs:
                return render_template(p.outputs['template'], vars=p.outputs['template_vars'])
            return render_template(p.outputs['template'], vars={})
    
    if filename is None and ext is None: 
        return render_template(TEMPLATE, vars={})
    elif filename == 'index' and ext == 'php':
        return render_template(TEMPLATE, vars={})
    else:        
        abort(404)

@app.route('/wp-admin', methods=['GET', 'POST'])
@app.route(r'/wp-admin<regex(r"\/.*"):subpath>', methods=['GET', 'POST'])
def admin(subpath='/'):
    """ Admin panel probing handler """
    origin = request.remote_addr
    LOGGER.info('%s probed for the admin panel with path: %s', origin, subpath)

    # Plugins hook
    for p in pm.hook('plugins'):
        p.start(subpath=subpath, request=request)
        if 'log' in p.outputs:
            LOGGER.info(p.outputs['log'])
        if 'log_json' in p.outputs:
            if app.config['HPFEEDS_ENABLED']:
                app.config['hpfeeds_client'].publish(app.config['HPFEEDS_TOPIC'], p.outputs['log_json'])
            LOGGER.info('%s', p.outputs['log_json'])
        if 'template' in p.outputs:
            if 'template_vars' in p.outputs:
                return render_template(p.outputs['template'], vars=p.outputs['template_vars']) 
            return render_template(p.outputs['template'], vars={})
    
    return redirect('wp-login.php')

@app.route('/wp-content/plugins/<plugin>', methods=['GET', 'POST'])
@app.route(r'/wp-content/plugins/<plugin><regex(r"(\/.*)"):subpath>', methods=['GET', 'POST'])
def plugin(plugin, subpath='/'):
    """ Plugin probing handler """
    origin = request.remote_addr
    LOGGER.info('%s probed for plugin "%s" with path: %s', origin, plugin, subpath)
    
    if not is_plugin_whitelisted(plugin):
        abort(404)

    for p in pm.hook('plugins'):
        p.start(plugin=plugin, subpath=subpath, request=request)
        if 'log' in p.outputs:
            LOGGER.info(p.outputs['log'])
        if 'log_json' in p.outputs:
            if app.config['HPFEEDS_ENABLED']:
                app.config['hpfeeds_client'].publish(app.config['HPFEEDS_TOPIC'], p.outputs['log_json'])
            LOGGER.info('%s', p.outputs['log_json'])
        if 'template' in p.outputs:
            if 'template_vars' in p.outputs:
                return render_template(p.outputs['template'], vars=p.outputs['template_vars'])
            return render_template(p.outputs['template'], vars={})

    return render_template(TEMPLATE, vars={})

@app.route('/wp-content/themes/<theme>', methods=['GET', 'POST'])
@app.route(r'/wp-content/themes/<theme><regex(r"(\/.*)"):subpath>', methods=['GET', 'POST'])
def theme(theme, subpath='/'):
    """ Theme probing handler """
    origin = request.remote_addr
    LOGGER.info('%s probed for theme "%s" with path: %s', origin, theme, subpath)

    if not is_theme_whitelisted(theme):
        abort(404)

    for p in pm.hook('themes'):
        p.start(theme=theme, subpath=subpath, request=request)
        if 'log' in p.outputs:
            LOGGER.info(p.outputs['log'])
        if 'log_json' in p.outputs:
            if app.config['HPFEEDS_ENABLED']:
                app.config['hpfeeds_client'].publish(app.config['HPFEEDS_TOPIC'], p.outputs['log_json'])
            LOGGER.info('%s', p.outputs['log_json'])
        if 'template' in p.outputs:
            if 'template_vars' in p.outputs:
                return render_template(p.outputs['template'], vars=p.outputs['template_vars'])
            return render_template(p.outputs['template'], vars={})

    return render_template(TEMPLATE, vars={})

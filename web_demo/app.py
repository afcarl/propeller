'''
Web frontend for the image classifier. Posts images to be classified to the redis server,
which the workers read from.

Author: Axel.Tidemann@telenor.com, Cyril.Banino-Rokkones@telenor.com
'''

import os
import time
import cPickle as pickle
from collections import namedtuple
import datetime
import logging
import argparse
import cStringIO as StringIO
import urllib
import random
from functools import wraps
import threading
from collections import defaultdict

from flask import request, Response
import flask
import werkzeug
import redis
import tornado.wsgi
import tornado.httpserver
import tornado.web
import tornado.websocket


# For the position of the word webs
OFFSET = 800

# Timeout seconds for waiting on the redis key
TIMEOUT = 5

# Obtain the flask app object
app = flask.Flask(__name__)

listeners = []

def redis_listener(server, port):
    logging.info('redis listener started')
    _red = redis.StrictRedis(server, port)
    _pubsub = _red.pubsub(ignore_subscribe_messages=True)
    _pubsub.subscribe('latest')
    for msg in _pubsub.listen():
        result = pickle.loads(msg['data'])
        # We must unfortunately format the string here, due to the async nature/JavaScript combination.
        display = '<SPAN style="width:200px; float:left; text-align:center;">{}<BR><A HREF="{}"><IMG SRC="{}" TITLE="{}" WIDTH=200></A></SPAN>'.format(
            result['category'], result['path'], result['path'], result['value'])
        for socket in listeners:
            socket.write_message(display)

class WebSocket(tornado.websocket.WebSocketHandler):
    def open(self):
        logging.info("Socket opened, starting to listen to redis channel.")
        listeners.append(self)

    def on_message(self, message):
        logging.info("Received message: " + message)

    def on_close(self):
        logging.info("Socket closed.")
        listeners.remove(self)

@app.template_filter('split_path')
def split_path(path):
    full_path = ''
    hrefs = []
    for s in path.split('/'):
        if len(s):
            full_path += '/{}'.format(s)
            hrefs.append([s, full_path])

    hrefs.insert(0, ['~', '/'])
    return hrefs

@app.template_filter('commastrip')
def commastrip(path):
    return path[:path.find(',')] if ',' in path else path

# Remove caching
@app.after_request
def add_header(response):
    response.cache_control.max_age = 0
    return response

def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return username == 'telenor' and password == 'research'

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Ask for credentials.', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    return flask.render_template('index.html', has_result=False)

@app.route('/embeddings')
@app.route('/embeddings/wow') # To remove when more categories are included
@requires_auth
def embeddings():
    return flask.render_template('wow.html', has_result=False)

@app.route('/embeddings/wow/<path:bu>')
@requires_auth
def show_word(bu):
    return flask.render_template("network.html", bu=bu)

def get_neighbors(word, nodes, links, pos, level, bu):
    neighbors = red.hgetall(str("wow:"+bu+":") + word)
    neighbors = sorted(neighbors.items(), key=lambda x: x[1])[:7]
    for n in neighbors:
        name = n[0]
        if name not in pos and level > 0:
            nodes.append({"name":name, "x":OFFSET*random.random() , "y":OFFSET*random.random(), "distan\
ce":round(float(n[1]), 2), "to":word})
            pos[name] = len(nodes)-1
        if name in pos:
            links.append({"source":pos[word],"target":pos[name],"value":1.0-float(n[1])})

    if level == 0:
        return

    for n in neighbors:
        get_neighbors(str(n[0]), nodes, links, pos, level-1, bu)


@app.route('/embeddings/wow/json/<path:bu>/<path:word>')
@requires_auth
def get_json(bu, word):
    word = word.strip().lower().encode("utf-8")

    if word == "_":
        word = red.srandmember('wow:'+bu+':vocab')

    tmp = {}
    nodes = []
    nodes.append({"name": word, "x":OFFSET*random.random() , "y":OFFSET*random.random(), "distance":0.0\
, "to":"self"})
    tmp[word] = 0
    links = []
    get_neighbors(word, nodes, links, tmp, 2, bu)
    return flask.jsonify({"nodes":nodes, "links":links})


################################### Network Utilization ###########################################
    
@app.route('/network/telenorbulgaria')
@requires_auth
def render_network_usage():
        return flask.render_template("bulgaria.html")


@app.route('/telenor/research/bulgaria/json/<path:threshold_obs>/<path:distance_min>/<path:distance_max>/<path:traj_min>/<path:traj_max>')
def get_json_bulgaria(threshold_obs, distance_min, distance_max, traj_min, traj_max):
    threshold_obs = int(threshold_obs.strip().encode("utf-8"))
    distance_min = float(distance_min.strip().encode("utf-8"))
    distance_max = float(distance_max.strip().encode("utf-8"))
    traj_min = traj_min.strip().encode("utf-8")
    traj_max = traj_max.strip().encode("utf-8")
    
    union_key = "bulgaria_trajectories:" + traj_min + "-" + traj_max
    if red_db_1.zcard(union_key) == 0:
        keys = []
        for t_l in range(int(traj_min), int(traj_max)):
            keys.append("bulgaria_trajectories:" + str(t_l))
        red_db_1.zunionstore(union_key, keys)

    edges_union = red_db_1.zrevrangebyscore(union_key, "+inf", threshold_obs, withscores=True)

    edges = defaultdict(lambda: 0)
    for e in edges_union:
        edges[e[0]] = e[1]
        
    edges_dist = set(red_db_1.zrangebyscore("bulgaria_network:edges_dist", distance_min, distance_max))

    for e in edges.keys():
        if edges[e] < threshold_obs or not(e in edges_dist):
            del edges[e]

    print "kept", len(edges), "edges"

    return flask.jsonify({"edges":edges})
        
@app.route('/telenor/research/bulgaria2/json/<path:threshold_obs>/<path:distance_min>/<path:distance_max>')
def get_json_bulgaria2(threshold_obs, distance_min, distance_max):
    threshold_obs = int(threshold_obs.strip().encode("utf-8"))-1
    distance_min = float(distance_min.strip().encode("utf-8"))
    distance_max = float(distance_max.strip().encode("utf-8"))
    
    vertices = red_db_1.zrevrangebyscore("bulgaria_network:vertices", "+inf", threshold_obs, withscores=True)
    print "got", len(vertices), "vertices"
    edges_obs = red_db_1.zrevrangebyscore("bulgaria_network:edges", "+inf", threshold_obs, withscores=True)
    print "got", len(edges_obs), "edges_obs"
    edges_dist = set(red_db_1.zrangebyscore("bulgaria_network:edges_dist", distance_min, distance_max))
    print "got", len(edges_dist), "edges_dist"

    kept_edges = [x for x in edges_obs if x[0] in edges_dist]
    print "kept", len(kept_edges), "edges"
    return flask.jsonify({"vertices":vertices, "edges":kept_edges})
                                                    

################################### Images ###########################################
    
@app.route('/images')
@requires_auth
def classify_image():
    return flask.render_template('classify_image.html', has_result=False)

@app.route('/images/live')
@requires_auth
def socket():
    return flask.render_template('socket.html')

@app.route('/images/restful_api')
@requires_auth
def restful():
    return flask.render_template('restful.html')

@app.route('/images/categories')
@requires_auth
def categories():
    result = red.keys('archive:web:category:*')
    result = sorted([ cat[cat.rfind(':')+1:] for cat in result ],
                    key=lambda s: s.lower())
    return flask.render_template('categories.html', result=result)


def get_images_from_category(category, num=-1, group='web'):
    result = red.zrevrangebyscore('archive:{}:category:{}'.format(group, category),
                                  1, 0, start=0, num=num, withscores=True)
    return [ (unicode(url, 'utf-8'), score) for url, score in result ]
    

@app.route('/images/categories/<path:category>/')
@requires_auth
def images(category):
    return flask.render_template('images.html', category=category, result=get_images_from_category(category))

def wait_for_prediction(group, path):
    key = 'archive:{}:{}'.format(group, path)
    t0 = time.time()
    while True:
        if red.exists(key):
            return red.hgetall(key)
        if time.time() - t0 > TIMEOUT:
            return {'OK': 'False'}
        time.sleep(.1)

def parse_result(result):
    if eval(result['OK']):
        return (eval(result['OK']), eval(result['predictions']), eval(result['computation_time']))
    return (False, 'Something went wrong when classifying the image.')
    
@app.route('/images/archive/<path:group>/<path:path>')
@requires_auth
def prediction(group, path):
    response = wait_for_prediction(group, path)
    if 'predictions' in response:
        predictions = eval(response['predictions'])
        json_preds = {}
        for p in predictions:
            json_preds[p[0]] = p[1]
        return flask.jsonify({'predictions': json_preds})

    error = {
        'group':group,
        'path': path,
        'message': 'You must submit the picture in \'path\' for classification first with the classify.py script.'
    }
    return flask.jsonify({'error': error})

@app.route('/images/archive/<path:group>/category/<path:category>')
@requires_auth
def images_in_category(group, category):
    return '\n'.join(red.zrevrangebyscore('archive:{}:category:{}'.format(group, category), 1, 0))

@app.route('/images/classify', methods=['POST'])
@requires_auth
def classify():
    my_file = StringIO.StringIO(request.files['file'].read())

    i = 0
    for line in my_file:
        task = {'group': request.form['group'], 'path': line.strip()}
        if i == 0: 
            pipe.rpush(args.queue, pickle.dumps(task))
        else: 
            pipe.lpush(args.queue, pickle.dumps(task))

        i += 1
        if i % 10000 == 0:
            pipe.execute()
            logging.info('Piping 10K items to redis.')

    pipe.execute()
    return '{} images queued for classification.'.format(i)

@app.route('/images/classify_url', methods=['GET'])
@requires_auth
def classify_url():
    imageurl = flask.request.args.get('imageurl', '')
    red.rpush(args.queue, pickle.dumps({'group': 'web', 'path': imageurl})) # SPECS COMMON!

    prediction = wait_for_prediction('web', imageurl)
    result = parse_result(prediction)
    similar = get_images_from_category(result[1][0][0], 10)
    return flask.render_template(
        'classify_image.html', has_result=True, result=result, imagesrc=imageurl, 
        similar=similar)

def start_tornado(app, port=5000):
    container = tornado.wsgi.WSGIContainer(app)
    server = tornado.web.Application([
        (r'/websocket', WebSocket),
        (r'.*', tornado.web.FallbackHandler, dict(fallback=container))
    ])
    server.listen(port)
    logging.info("Tornado server starting on port {}".format(port))
    tornado.ioloop.IOLoop.instance().start()

logging.getLogger().setLevel(logging.INFO)
logging.basicConfig(format='%(asctime)s %(message)s')

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument(
    '-d', '--debug',
    help="enable debug mode",
    action="store_true", default=False)
parser.add_argument(
    '-p', '--port',
    help="which port to serve content on",
    type=int, default=5000)
parser.add_argument(
    '-rs', '--redis_server',
    help='the redis server address',
    default='localhost')
parser.add_argument(
    '-rp', '--redis_port',
    help='the redis port',
    default='6379')
parser.add_argument(
    '-q', '--queue',
    help='redis queue to post image classification tasks to',
    default='classify')

args = parser.parse_args()

red = redis.StrictRedis(args.redis_server, args.redis_port)
red_db_1 = redis.StrictRedis(args.redis_server, args.redis_port, db=1)
pubsub = red.pubsub(ignore_subscribe_messages=True)
pipe = red.pipeline()

threading.Thread(target=redis_listener, args=(args.redis_server, args.redis_port)).start()

if args.debug:
    app.run(debug=True, host='0.0.0.0', port=args.port)
else:
    start_tornado(app, args.port)



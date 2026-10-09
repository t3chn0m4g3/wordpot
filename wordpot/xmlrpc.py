"""Small, non-networking WordPress XML-RPC response emulator."""

from xmlrpc.client import Fault, dumps, loads

from defusedxml.xmlrpc import monkey_patch


monkey_patch()

WORDPRESS_METHODS = [
    "blogger.deletePost", "blogger.getUsersBlogs", "blogger.getRecentPosts",
    "blogger.getPost", "blogger.newPost", "blogger.editPost",
    "metaWeblog.newPost", "metaWeblog.editPost", "metaWeblog.getPost",
    "metaWeblog.getRecentPosts", "metaWeblog.getCategories", "metaWeblog.newMediaObject",
    "mt.getRecentPostTitles", "mt.getCategoryList", "mt.getPostCategories",
    "mt.setPostCategories", "mt.supportedMethods", "mt.supportedTextFilters",
    "wp.getUsersBlogs", "wp.getProfile", "wp.getAuthors", "wp.getCategories",
    "wp.getTags", "wp.newCategory", "wp.deleteCategory", "wp.getPage", "wp.getPages",
    "wp.newPage", "wp.deletePage", "wp.editPage", "wp.getPageList", "wp.getComments",
    "wp.getCommentCount", "wp.getPostStatusList", "wp.getPageStatusList",
    "wp.getPageTemplates", "wp.getOptions", "wp.setOptions", "wp.getComment",
    "wp.newComment", "wp.editComment", "wp.deleteComment", "wp.getMediaLibrary",
    "wp.getPostFormats", "wp.getPost", "wp.getPosts", "wp.newPost", "wp.deletePost",
    "wp.editPost", "system.multicall", "system.listMethods", "system.methodSignature",
    "system.methodHelp", "demo.sayHello", "pingback.ping", "pingback.extensions.getPingbacks",
]

LOGIN_METHODS = {"wp.getUsersBlogs", "wp.getProfile"}
LOGIN_FAULT = Fault(403, "Incorrect username or password.")
PINGBACK_FAULT = Fault(0, "Is your site configured correctly?")


def parse_call(body):
    """Parse one XML-RPC call using defusedxml's patched parser."""
    params, method_name = loads(body)
    if not isinstance(method_name, str):
        raise ValueError("Missing XML-RPC method name")
    return method_name, params


def credential_pair_for_call(call):
    if not isinstance(call, dict) or call.get("methodName") not in LOGIN_METHODS:
        return None
    params = call.get("params")
    if not isinstance(params, (list, tuple)) or len(params) < 2:
        return None
    username, password = params[-2], params[-1]
    return {"username": str(username), "password": str(password)}


def response(value):
    return dumps((value,), methodresponse=True, allow_none=True, encoding="utf-8")


def fault_response(fault):
    return dumps(fault, methodresponse=True, allow_none=True, encoding="utf-8")


def multicall_response(calls):
    fault = {"faultCode": 403, "faultString": "Incorrect username or password."}
    return response([dict(fault) for _call in calls])

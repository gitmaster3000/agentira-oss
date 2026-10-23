// Sign-in handoff to the MCP service: an MCP client sent the user to <mcp>/authorize; if they are already
// signed in here, POST their login to <mcp>/authorize/sso (form POST: the token never lands in a URL, history
// or Referer) instead of asking for the password again. Only ever posts to the configured MCP address.

// The authorize URL (on the MCP service) this page was asked to continue, or null if it is not that service.
export function mcpAuthorizeTarget(returnUrl, mcpUrl) {
    try {
        const target = new URL(returnUrl);
        const mcp = new URL(mcpUrl);
        return target.origin === mcp.origin && target.pathname === '/authorize' ? target : null;
    } catch {
        return null;
    }
}

export function postToMcp(target, { token = localStorage.getItem('agentira_token'), doc = document } = {}) {
    const form = doc.createElement('form');
    form.method = 'POST';
    form.action = `${target.origin}/authorize/sso`;
    const add = (name, value) => {
        const input = doc.createElement('input');
        input.type = 'hidden'; input.name = name; input.value = value;
        form.appendChild(input);
    };
    for (const [k, v] of target.searchParams) if (k !== 'sso') add(k, v);
    add('token', token);
    doc.body.appendChild(form);
    form.submit();
    form.remove();
}

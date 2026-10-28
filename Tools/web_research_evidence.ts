/** Versioned export policy shared by CLI, index/captures and MCP delivery. */
export const SANITIZER_VERSION = "agency/evidence-sanitizer/1";
export function sensitiveEvidenceKey(name: string) {
  return /(?:^|[_-])(?:(?:access|auth|id|refresh)[_-]?)?token(?:$|[_-])|(?:^|[_-])(?:api[_-]?key|password|passwd|captcha|challenge|credential|secret|signature|sig|solution)(?:$|[_-])|^(?:authorization|bearer|cookie|set-cookie|awsaccesskeyid|key-pair-id|cf_chl_|jsc_|session|trkinfo)/i.test(name);
}
export function sanitizeEvidence<T>(input: T): { value: T; redaction: { version: string; count: number } } {
  let count = 0;
  const decode = (value: string) => {
    for (let pass = 0; pass < 6; pass++) {
      let next = value.replace(/\\u([\da-f]{4})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
        .replace(/\\\//g, "/")
        .replace(/&#(x[\da-f]+|\d+);/gi, (whole, number) => {
          const point = number.toLowerCase().startsWith("x") ? parseInt(number.slice(1), 16) : Number(number);
          return point <= 0x10ffff ? String.fromCodePoint(point) : whole;
        }).replace(/&amp;/gi, "&").replace(/&colon;/gi, ":").replace(/&sol;/gi, "/");
      try { next = decodeURIComponent(next); } catch { /* Preserve malformed escapes for the URL parser. */ }
      if (next === value) break;
      value = next;
    }
    return value;
  };
  const string = (value: string) => value.replace(/https?(?::|%(?:25)*3a|\\u003a|&(?:colon|#0*58|#x0*3a);)(?:\/|\\\/|%(?:25)*2f|\\u002f|&(?:sol|#0*47|#x0*2f);){2}[^\s<>"')\]]*/gi, raw => {
    const decoded = decode(raw);
    try {
      const url = new URL(decoded);
      if (!['https:', 'http:'].includes(url.protocol)) return raw;
      let changed = decoded !== raw;
      if (url.username || url.password) { count++; url.username = ''; url.password = ''; changed = true; }
      for (const name of [...url.searchParams.keys()]) {
        if (sensitiveEvidenceKey(decode(name))) { count++; url.searchParams.delete(name); changed = true; }
      }
      // Fragments may contain OAuth material; stable document selectors belong in the query.
      if (url.hash && /(?:token|secret|sig|credential|authorization)=/i.test(decode(url.hash))) {
        count++; url.hash = ''; changed = true;
      }
      return changed ? url.href : raw;
    } catch { return raw; }
  }).replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, () => { count++; return 'Bearer [redacted]'; });
  const visit = (value: any): any => {
    if (typeof value === 'string') return string(value);
    if (Array.isArray(value)) return value.map(visit);
    if (value && typeof value === 'object') {
      const result: Record<string, any> = {};
      for (const [key, item] of Object.entries(value)) {
        const fileValidationStatus = key === 'signature' && item === 'valid'
          && typeof value.sha256 === 'string' && /^[0-9a-f]{64}$/i.test(value.sha256)
          && typeof value.bytes === 'number' && typeof value.expected_type === 'string';
        if (sensitiveEvidenceKey(decode(key)) && !fileValidationStatus) {
          if (item !== '[redacted]') count++;
          result[key] = '[redacted]';
        } else result[key] = visit(item);
      }
      return result;
    }
    return value;
  };
  return { value: visit(input) as T, redaction: { version: SANITIZER_VERSION, count } };
}

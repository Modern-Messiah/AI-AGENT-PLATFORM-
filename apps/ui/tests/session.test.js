import test from 'node:test'
import assert from 'node:assert/strict'

import {
  decodeJwtPayload,
  parseSessionHash,
  sessionClaimsValid,
} from '../src/stores/session.js'


function makeToken(claims = {}, headerAlter = false) {
  const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url')
  const defaultClaims = {
    type: 'session',
    sub: 'u-1',
    tid: 'main',
    email: 'a@x.io',
    name: 'A',
    role: 'member',
    exp: Math.floor(Date.now() / 1000) + 3600,
  }
  const token = [b64({ alg: 'HS256', typ: 'JWT' }), b64({ ...defaultClaims, ...claims })]
  if (headerAlter) token[0] = b64({})
  return `${token[0]}.${token[1]}.sig`
}


test('parseSessionHash extracts token and error fragments', () => {
  assert.deepEqual(parseSessionHash('#token=abc.def'), { token: 'abc.def', error: null })
  assert.deepEqual(parseSessionHash('#error=access%20denied'), {
    token: null,
    error: 'access denied',
  })
  assert.deepEqual(parseSessionHash(''), { token: null, error: null })
  assert.deepEqual(parseSessionHash('#/whatever'), { token: null, error: null })
})


test('decodeJwtPayload reads claims and rejects junk', () => {
  const claims = decodeJwtPayload(makeToken({ role: 'admin' }))
  assert.equal(claims.role, 'admin')
  assert.equal(claims.tid, 'main')
  assert.equal(decodeJwtPayload('not-a-token'), null)
  assert.equal(decodeJwtPayload(''), null)
})


test('sessionClaimsValid enforces type and expiry', () => {
  const now = Date.now()
  assert.equal(sessionClaimsValid({ type: 'session', exp: now / 1000 + 60 }, now), true)
  assert.equal(sessionClaimsValid({ type: 'session', exp: now / 1000 - 60 }, now), false)
  assert.equal(sessionClaimsValid({ type: 'state', exp: now / 1000 + 60 }, now), false)
  assert.equal(sessionClaimsValid(null, now), false)
  assert.equal(sessionClaimsValid({ type: 'session' }, now), false)
})

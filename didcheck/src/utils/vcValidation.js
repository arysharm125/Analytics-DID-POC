/**
 * VC Validation Utilities
 *
 * Provides validation functions for Verifiable Credentials
 */

import { verifyVCProof } from './proofVerification.js'

// DID patterns
const AMD_DID_PREFIX = 'did:web:did.amd.com'
const AMD_DID_PATTERN = /^did:web:did\.amd\.com:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Parse a VC file and return the parsed JSON
 * @param {File} file - The file to parse
 * @returns {Promise<{success: boolean, data?: object, error?: string}>}
 */
export async function parseVCFile(file) {
  try {
    const text = await file.text()
    const data = JSON.parse(text)
    return { success: true, data }
  } catch (err) {
    return {
      success: false,
      error: err instanceof SyntaxError
        ? `Invalid JSON: ${err.message}`
        : `Failed to read file: ${err.message}`
    }
  }
}

/**
 * Validation result for a single check
 * @typedef {Object} ValidationCheck
 * @property {string} name - The name of the check
 * @property {boolean} passed - Whether the check passed
 * @property {string} message - Description of the result
 * @property {string} [value] - The actual value found (if applicable)
 */

/**
 * Full validation result
 * @typedef {Object} ValidationResult
 * @property {boolean} valid - Whether all required checks passed
 * @property {ValidationCheck[]} checks - Array of individual check results
 * @property {string|null} versionUid - Extracted versionUid if found
 */

/**
 * Validate VC structure and content
 * @param {object} vc - The parsed VC object
 * @returns {Promise<ValidationResult>}
 */
export async function validateVCStructure(vc) {
  const checks = []
  let versionUid = null

  // Check 1: Type field validation
  const typeCheck = validateTypeField(vc)
  checks.push(typeCheck)

  // Check 2: Issuer validation
  const issuerCheck = validateIssuer(vc)
  checks.push(issuerCheck)

  // Check 3: credentialSubject.id validation
  const subjectIdCheck = validateCredentialSubjectId(vc)
  checks.push(subjectIdCheck)

  // Check 4: versionUid validation
  const versionUidCheck = validateVersionUid(vc)
  checks.push(versionUidCheck)
  if (versionUidCheck.passed && versionUidCheck.value) {
    versionUid = versionUidCheck.value
  }

  // Check 5: Proof verification (cryptographic signature validation)
  const proofCheck = await validateProof(vc)
  checks.push(proofCheck)

  // Calculate overall validity (all checks must pass)
  const valid = checks.every(c => c.passed)

  return { valid, checks, versionUid }
}

/**
 * Validate the cryptographic proof of the VC
 * @param {object} vc - The parsed VC object
 * @returns {Promise<ValidationCheck>}
 */
async function validateProof(vc) {
  // First check if proof exists
  if (!vc.proof) {
    return {
      name: 'Proof Verification',
      passed: false,
      message: 'Missing "proof" field'
    }
  }

  // Verify the cryptographic proof
  const result = await verifyVCProof(vc)

  if (result.verified) {
    return {
      name: 'Proof Verification',
      passed: true,
      message: 'Cryptographic signature is valid',
      value: result.details?.verificationMethod
    }
  } else {
    return {
      name: 'Proof Verification',
      passed: false,
      message: result.error || 'Proof verification failed'
    }
  }
}

/**
 * Validate the "type" field includes required types
 * @param {object} vc
 * @returns {ValidationCheck}
 */
function validateTypeField(vc) {
  const type = vc.type

  if (!type) {
    return {
      name: 'Type Field',
      passed: false,
      message: 'Missing "type" field'
    }
  }

  const types = Array.isArray(type) ? type : [type]
  const hasVerifiableCredential = types.includes('VerifiableCredential')
  const hasDigitalArtefactCredential = types.includes('DigitalArtefactCredential')

  if (!hasVerifiableCredential && !hasDigitalArtefactCredential) {
    return {
      name: 'Type Field',
      passed: false,
      message: `Type must include "VerifiableCredential" and "DigitalArtefactCredential". Found: ${types.join(', ')}`
    }
  }

  if (!hasVerifiableCredential) {
    return {
      name: 'Type Field',
      passed: false,
      message: 'Type must include "VerifiableCredential"'
    }
  }

  if (!hasDigitalArtefactCredential) {
    return {
      name: 'Type Field',
      passed: false,
      message: 'Type must include "DigitalArtefactCredential"'
    }
  }

  return {
    name: 'Type Field',
    passed: true,
    message: 'Type includes "VerifiableCredential" and "DigitalArtefactCredential"',
    value: types.join(', ')
  }
}

/**
 * Validate the issuer field is an AMD DID
 * @param {object} vc
 * @returns {ValidationCheck}
 */
function validateIssuer(vc) {
  const issuer = typeof vc.issuer === 'string' ? vc.issuer : vc.issuer?.id

  if (!issuer) {
    return {
      name: 'Issuer',
      passed: false,
      message: 'Missing "issuer" field'
    }
  }

  if (!issuer.startsWith(AMD_DID_PREFIX)) {
    return {
      name: 'Issuer',
      passed: false,
      message: `Issuer must start with "${AMD_DID_PREFIX}". Found: ${issuer}`
    }
  }

  return {
    name: 'Issuer',
    passed: true,
    message: 'Issuer is a valid AMD DID',
    value: issuer
  }
}

/**
 * Validate credentialSubject.id is an AMD DID
 * @param {object} vc
 * @returns {ValidationCheck}
 */
function validateCredentialSubjectId(vc) {
  const subject = vc.credentialSubject

  if (!subject) {
    return {
      name: 'Credential Subject ID',
      passed: false,
      message: 'Missing "credentialSubject" field'
    }
  }

  const subjectId = subject.id

  if (!subjectId) {
    return {
      name: 'Credential Subject ID',
      passed: false,
      message: 'Missing "credentialSubject.id" field'
    }
  }

  if (!AMD_DID_PATTERN.test(subjectId)) {
    return {
      name: 'Credential Subject ID',
      passed: false,
      message: `credentialSubject.id must be a valid AMD DID (did:web:did.amd.com:<uuid>). Found: ${subjectId}`
    }
  }

  return {
    name: 'Credential Subject ID',
    passed: true,
    message: 'credentialSubject.id is a valid AMD DID',
    value: subjectId
  }
}

/**
 * Validate versionUid field exists in credentialSubject and is a valid AMD DID
 * @param {object} vc
 * @returns {ValidationCheck}
 */
function validateVersionUid(vc) {
  const subject = vc.credentialSubject

  if (!subject) {
    return {
      name: 'Version UID',
      passed: false,
      message: 'Missing "credentialSubject" field'
    }
  }

  const versionUid = subject.versionUid

  if (!versionUid) {
    return {
      name: 'Version UID',
      passed: false,
      message: 'Missing "credentialSubject.versionUid" field'
    }
  }

  // Validate it's a valid AMD DID format (did:web:did.amd.com:{uuid})
  if (!AMD_DID_PATTERN.test(versionUid)) {
    return {
      name: 'Version UID',
      passed: false,
      message: `versionUid must be a valid AMD DID (did:web:did.amd.com:<uuid>). Found: ${versionUid}`
    }
  }

  // Extract the UUID from the DID
  const extractedUid = extractUidFromDID(versionUid)

  return {
    name: 'Version UID',
    passed: true,
    message: 'versionUid is a valid AMD DID',
    value: extractedUid
  }
}

/**
 * Extract the UID from an AMD DID
 * @param {string} did - AMD DID string
 * @returns {string|null} The extracted UID or null if invalid
 */
export function extractUidFromDID(did) {
  if (!did || !did.startsWith(AMD_DID_PREFIX + ':')) return null
  return did.substring(AMD_DID_PREFIX.length + 1)
}

/**
 * Extract the VC's own ID (top-level "id" field) if it's a valid AMD DID
 * @param {object} vc - The parsed VC object
 * @returns {string|null} The extracted UUID or null if invalid/missing
 */
export function extractVCId(vc) {
  const vcId = vc?.id
  if (!vcId || typeof vcId !== 'string') return null

  // Validate it's a valid AMD DID format (did:web:did.amd.com:{uuid})
  if (!AMD_DID_PATTERN.test(vcId)) return null

  // Extract and return the UUID
  return extractUidFromDID(vcId)
}

export default {
  parseVCFile,
  validateVCStructure,
  extractUidFromDID,
  extractVCId
}

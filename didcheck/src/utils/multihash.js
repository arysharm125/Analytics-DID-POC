/**
 * Multihash utilities for parsing and verifying file hashes
 */

// Multihash algorithm codes (subset of common ones)
export const MULTIHASH_ALGORITHMS = {
  0x12: { name: 'sha2-256', webCrypto: 'SHA-256', length: 32 },
  0x13: { name: 'sha2-512', webCrypto: 'SHA-512', length: 64 },
  0x14: { name: 'sha3-512', webCrypto: null, length: 64 },
  0x15: { name: 'sha3-384', webCrypto: null, length: 48 },
  0x16: { name: 'sha3-256', webCrypto: null, length: 32 },
  0x17: { name: 'sha3-224', webCrypto: null, length: 28 },
  0x1b: { name: 'keccak-256', webCrypto: null, length: 32 },
  0xb220: { name: 'blake2b-256', webCrypto: null, length: 32 },
}

// Base58 alphabet (Bitcoin variant)
const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

/**
 * Convert hex string to Uint8Array
 * @param {string} hex - Hexadecimal string
 * @returns {Uint8Array}
 */
export const hexToBytes = (hex) => {
  const bytes = new Uint8Array(hex.length / 2)
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substr(i, 2), 16)
  }
  return bytes
}

/**
 * Convert Uint8Array to hex string
 * @param {Uint8Array} bytes
 * @returns {string}
 */
export const bytesToHex = (bytes) => {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Decode base58 string to bytes
 * @param {string} str - Base58 encoded string
 * @returns {Uint8Array}
 */
export const base58Decode = (str) => {
  const bytes = []

  for (const char of str) {
    let carry = BASE58_ALPHABET.indexOf(char)
    if (carry < 0) {
      throw new Error(`Invalid base58 character: ${char}`)
    }

    for (let i = 0; i < bytes.length; i++) {
      carry += bytes[i] * 58
      bytes[i] = carry & 0xff
      carry >>= 8
    }

    while (carry > 0) {
      bytes.push(carry & 0xff)
      carry >>= 8
    }
  }

  // Handle leading zeros
  for (const char of str) {
    if (char !== '1') break
    bytes.push(0)
  }

  return new Uint8Array(bytes.reverse())
}

/**
 * Parse a multihash from base16 (hex) or base58btc format
 * @param {string} multihashStr - The multihash string to parse
 * @returns {{ code: number, length: number, digest: Uint8Array }}
 */
export const parseMultihash = (multihashStr) => {
  let bytes

  // Try to detect format - if it starts with common base58 chars and no hex-only chars
  if (/^[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]+$/.test(multihashStr)) {
    // Base58btc - need to decode
    bytes = base58Decode(multihashStr)
  } else if (/^[0-9a-fA-F]+$/.test(multihashStr)) {
    // Hex format
    bytes = hexToBytes(multihashStr)
  } else {
    throw new Error('Unknown multihash encoding format')
  }

  if (bytes.length < 2) {
    throw new Error('Multihash too short')
  }

  // Parse varint for algorithm code
  let code = 0
  let offset = 0
  let shift = 0

  while (offset < bytes.length) {
    const byte = bytes[offset]
    code |= (byte & 0x7f) << shift
    offset++
    if ((byte & 0x80) === 0) break
    shift += 7
  }

  // Parse varint for length
  let length = 0
  shift = 0

  while (offset < bytes.length) {
    const byte = bytes[offset]
    length |= (byte & 0x7f) << shift
    offset++
    if ((byte & 0x80) === 0) break
    shift += 7
  }

  const digest = bytes.slice(offset)

  if (digest.length !== length) {
    throw new Error(`Digest length mismatch: expected ${length}, got ${digest.length}`)
  }

  return { code, length, digest }
}

/**
 * Hash a file using Web Crypto API
 * @param {File} file - The file to hash
 * @param {string} algorithm - The Web Crypto algorithm name (e.g., 'SHA-256')
 * @returns {Promise<Uint8Array>}
 */
export const hashFile = async (file, algorithm) => {
  const arrayBuffer = await file.arrayBuffer()
  const hashBuffer = await crypto.subtle.digest(algorithm, arrayBuffer)
  return new Uint8Array(hashBuffer)
}

/**
 * Compare two Uint8Arrays for equality
 * @param {Uint8Array} a
 * @param {Uint8Array} b
 * @returns {boolean}
 */
export const arraysEqual = (a, b) => {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false
  }
  return true
}

/**
 * Verify a file against a multihash
 * @param {File} file - The file to verify
 * @param {string} multihashStr - The multihash string to verify against
 * @returns {Promise<{ success: boolean, message: string, algorithmName?: string }>}
 */
export const verifyFileAgainstMultihash = async (file, multihashStr) => {
  // Parse the multihash
  const multihash = parseMultihash(multihashStr)

  // Get algorithm info
  const algorithmInfo = MULTIHASH_ALGORITHMS[multihash.code]
  if (!algorithmInfo) {
    throw new Error(`Unsupported hash algorithm code: 0x${multihash.code.toString(16)}`)
  }

  if (!algorithmInfo.webCrypto) {
    throw new Error(`Algorithm ${algorithmInfo.name} is not supported by Web Crypto API`)
  }

  // Hash the file
  const fileHash = await hashFile(file, algorithmInfo.webCrypto)

  // Compare hashes
  if (arraysEqual(fileHash, multihash.digest)) {
    return {
      success: true,
      message: `File verified successfully! Hash matches (${algorithmInfo.name}).`,
      algorithmName: algorithmInfo.name
    }
  } else {
    return {
      success: false,
      message: `Hash mismatch! The file does not match the registered artefact.
Expected: ${bytesToHex(multihash.digest)}
Got: ${bytesToHex(fileHash)}`,
      algorithmName: algorithmInfo.name
    }
  }
}

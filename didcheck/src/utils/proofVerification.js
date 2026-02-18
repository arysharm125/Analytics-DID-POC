/**
 * VC Proof Verification Utility
 * Uses @digitalbazaar/vc for cryptographic verification
 */

import { DataIntegrityProof } from '@digitalbazaar/data-integrity'
import { cryptosuite as eddsaRdfc2022CryptoSuite } from '@digitalbazaar/eddsa-rdfc-2022-cryptosuite'
import * as vc from '@digitalbazaar/vc'
import { documentLoader } from './documentLoader.js'

/**
 * Verification result
 * @typedef {Object} VerificationResult
 * @property {boolean} verified - Whether the proof is valid
 * @property {string} [error] - Error message if verification failed
 * @property {Object} [details] - Additional details about the verification
 * @property {string} [details.proofType] - The type of proof used
 * @property {string} [details.cryptosuite] - The cryptosuite used
 * @property {string} [details.verificationMethod] - The verification method used
 */

/**
 * Verify the cryptographic proof(s) on a Verifiable Credential
 *
 * This function verifies that:
 * 1. The VC has a valid DataIntegrityProof
 * 2. The signature is valid for the VC content
 * 3. The verification method exists and is authorized
 *
 * @param {object} credential - The VC to verify
 * @returns {Promise<VerificationResult>}
 */
export async function verifyVCProof(credential) {
  try {
    // Validate that the credential has a proof
    if (!credential.proof) {
      return {
        verified: false,
        error: 'Credential has no proof'
      }
    }

    // Check the proof type and cryptosuite
    const proofType = credential.proof.type
    const proofCryptosuite = credential.proof.cryptosuite

    // Currently only supporting DataIntegrityProof with eddsa-rdfc-2022
    if (proofType !== 'DataIntegrityProof') {
      return {
        verified: false,
        error: `Unsupported proof type: ${proofType}. Only DataIntegrityProof is supported.`
      }
    }

    if (proofCryptosuite !== 'eddsa-rdfc-2022') {
      return {
        verified: false,
        error: `Unsupported cryptosuite: ${proofCryptosuite}. Only eddsa-rdfc-2022 is supported.`
      }
    }

    // Create the DataIntegrityProof suite with eddsa-rdfc-2022 cryptosuite
    const suite = new DataIntegrityProof({ cryptosuite: eddsaRdfc2022CryptoSuite })

    // Verify the credential using @digitalbazaar/vc
    const result = await vc.verifyCredential({
      credential,
      suite,
      documentLoader
    })

    if (result.verified) {
      return {
        verified: true,
        details: {
          proofType: credential.proof.type,
          cryptosuite: credential.proof.cryptosuite,
          verificationMethod: credential.proof.verificationMethod,
          created: credential.proof.created
        }
      }
    } else {
      // Extract error message from the verification result
      let errorMessage = 'Proof verification failed'

      if (result.error) {
        if (result.error.errors && result.error.errors.length > 0) {
          // Collect all error messages
          const messages = result.error.errors
            .map(e => e.message || String(e))
            .filter(Boolean)
          errorMessage = messages.join('; ') || errorMessage
        } else if (result.error.message) {
          errorMessage = result.error.message
        }
      }

      return {
        verified: false,
        error: errorMessage
      }
    }
  } catch (error) {
    // Handle unexpected errors during verification
    let errorMessage = 'Unexpected error during proof verification'

    if (error.message) {
      errorMessage = error.message
    }

    // Check for common error patterns and provide helpful messages
    if (errorMessage.includes('Unable to load document')) {
      errorMessage = `Document resolution failed: ${errorMessage}`
    } else if (errorMessage.includes('Verification method not found')) {
      errorMessage = `Invalid verification method: ${errorMessage}`
    } else if (errorMessage.includes('Failed to fetch DID document')) {
      errorMessage = `Cannot fetch issuer DID document: ${errorMessage}`
    }

    return {
      verified: false,
      error: errorMessage
    }
  }
}

export default {
  verifyVCProof
}

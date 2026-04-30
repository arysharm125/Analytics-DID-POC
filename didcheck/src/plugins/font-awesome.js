// src/plugins/font-awesome.js
import { library } from '@fortawesome/fontawesome-svg-core'
import { faInstagram, faLinkedinIn, faTwitch, faYoutube, faFacebookF } from '@fortawesome/free-brands-svg-icons'
import { faEnvelope } from '@fortawesome/free-regular-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

// Add individual icons
library.add(faInstagram, faLinkedinIn, faTwitch, faYoutube, faFacebookF, faEnvelope)

export { FontAwesomeIcon }

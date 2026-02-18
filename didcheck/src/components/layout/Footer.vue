<template>
  <v-footer dark style="padding: 0; display: flex; align-items: center">
    <v-container id="footer-container" fluid style="background-color: black">
      <!-- Social Icons Row -->
      <v-row>
        <v-col cols="12" md="7" sm="0" class="d-none d-md-flex">
        </v-col>
        <v-col cols="12" md="5" sm="12" class="d-flex justify-center align-center">
          <ul class="social-menu" style="list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: nowrap;">
            <li style="padding: 0 0.5rem">
              <a
                id="footer-fb-link"
                href="https://www.facebook.com/amd"
                target="_blank"
                rel="noopener noreferrer"
                style="color: white"
              >
                <i class="fab fa-facebook-f"></i>
              </a>
            </li>
            <li style="padding: 0 0.5rem">
              <a
                id="footer-instagram-link"
                href="https://www.instagram.com/amd"
                target="_blank"
                rel="noopener noreferrer"
                style="color: white"
              >
                <i class="fab fa-instagram"></i>
              </a>
            </li>
            <li style="padding: 0 0.5rem">
              <a
                id="footer-linkedin-link"
                href="https://www.linkedin.com/company/amd"
                target="_blank"
                rel="noopener noreferrer"
                style="color: white"
              >
                <i class="fab fa-linkedin-in"></i>
              </a>
            </li>
            <li style="padding: 0 0.5rem">
              <a
                id="footer-twitch-link"
                href="https://www.twitch.tv/amd"
                target="_blank"
                rel="noopener noreferrer"
                style="color: white"
              >
                <i class="fab fa-twitch"></i>
              </a>
            </li>
            <li style="padding: 0 0.5rem">
              <a
                id="footer-twitter-link"
                href="https://twitter.com/amd"
                target="_blank"
                rel="noopener noreferrer"
                style="color: white"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor"
                  class="bi bi-twitter-x" viewBox="0 0 16 16">
                  <path
                    d="M12.6.75h2.454l-5.36 6.142L16 15.25h-4.937l-3.867-5.07-4.425 5.07H.316l5.733-6.57L0 .75h5.063l3.495 4.633L12.601.75Zm-.86 13.028h1.36L4.323 2.145H2.865z" />
                </svg>
              </a>
            </li>
            <li style="padding: 0 0.5rem">
              <a
                id="footer-youtube-link"
                href="https://www.youtube.com/user/amd?sub_confirmation=1"
                target="_blank"
                rel="noopener noreferrer"
                style="color: white"
              >
                <i class="fab fa-youtube"></i>
              </a>
            </li>
            <li style="padding: 0 0.5rem">
              <a
                id="footer-preferences-link"
                href="https://www.amd.com/en/preferences.html"
                target="_blank"
                rel="noopener noreferrer"
                style="color: white"
              >
                <i class="far fa-envelope"></i>
              </a>
            </li>
          </ul>
        </v-col>
      </v-row>

      <v-row style="padding-top: 80px"></v-row>

      <!-- Desktop Footer Links -->
      <v-row
        class="d-none d-md-flex d-lg-flex"
        style="display: flex; justify-content: center"
      >
        <v-col md="2" sm="2" class="footer-column">
          <h4 class="footer-sub-header">Company</h4>
          <div class="d-flex flex-column fotter-class">
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/corporate.html"
              >About AMD</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/corporate/leadership.html"
              >Management Team</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/corporate/corporate-responsibility.html"
              >Corporate Responsibility</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://careers.amd.com/careers-home"
              >Careers</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/corporate/contacts.html"
              >Contact Us</a
            >
          </div>
        </v-col>
        <v-col md="2" sm="2" class="footer-column">
          <h4 class="footer-sub-header">News & Events</h4>
          <div class="d-flex flex-column fotter-class">
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/newsroom.html"
              >Newsroom</a
            >
            <a href="https://www.amd.com/en/corporate/events.html">Events</a>
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://community.amd.com/t5/blogs/ct-p/amd-blogs"
              >Blogs</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/newsroom/media-library.html"
              >Media Library</a
            >
          </div>
        </v-col>
        <v-col md="2" sm="2" class="footer-column">
          <h4 class="footer-sub-header">Community</h4>
          <div class="d-flex flex-column fotter-class">
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://community.amd.com/t5/support-forums/ct-p/supprtforums"
              >Support</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://community.amd.com/t5/developers/ct-p/devgurus"
              >Developer</a
            >
            <a href="https://community.amd.com/t5/red-team/ct-p/red-team"
              >Red Team</a
            >
          </div>
        </v-col>
        <v-col md="2" sm="2" class="footer-column">
          <h4 class="footer-sub-header">Partners</h4>
          <div class="d-flex flex-column fotter-class">
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/developer.html"
              >Developers Center</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/partner.html"
              >AMD Partner Hub</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://www.amd.com/en/partner/about-partners/authorized-distributors.html"
              >Authorized Distributors</a
            >
            <a href="https://www.amd.com/en/corporate/university-program.html"
              >AMD University Program</a
            >
          </div>
        </v-col>
        <v-col md="2" sm="2" class="footer-column">
          <h4 class="footer-sub-header">Investors</h4>
          <div class="d-flex flex-column fotter-class">
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://ir.amd.com/"
              >Investor Relations</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://ir.amd.com/financial-information"
              >Financial Information</a
            >
            <a href="https://ir.amd.com/leadership-governance/board-of-directors"
              >Board of Directors</a
            >
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://ir.amd.com/leadership-governance/governance-documents"
              >Governance Documents</a
            >
            <a href="https://ir.amd.com/sec-filings">SEC Filings</a>
          </div>
        </v-col>
      </v-row>

      <!-- Mobile Footer Links -->
      <v-row
        style="display: flex; justify-content: center"
        class="d-block d-sm-flex d-xs-flex d-md-none d-lg-none"
      >
        <v-col>
          <v-expansion-panels theme="dark">
            <v-expansion-panel>
              <v-expansion-panel-title> Company </v-expansion-panel-title>
              <v-expansion-panel-text>
                <ul style="list-style-type: none; padding-left: 0">
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://www.amd.com/en/corporate.html"
                      >About AMD</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://www.amd.com/en/corporate/leadership.html"
                      >Management Team</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://careers.amd.com/careers-home"
                      >Careers</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://www.amd.com/en/corporate/contacts.html"
                      >Contact Us</a
                    >
                  </li>
                </ul>
              </v-expansion-panel-text>
            </v-expansion-panel>
            <v-expansion-panel>
              <v-expansion-panel-title> News & Events </v-expansion-panel-title>
              <v-expansion-panel-text>
                <ul style="list-style-type: none; padding-left: 0">
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://www.amd.com/en/newsroom.html"
                      >Newsroom</a
                    >
                  </li>
                  <li>
                    <a href="https://www.amd.com/en/corporate/events.html"
                      >Events</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://community.amd.com/t5/blogs/ct-p/amd-blogs"
                      >Blogs</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://www.amd.com/en/newsroom/media-library.html"
                      >Media Library</a
                    >
                  </li>
                </ul>
              </v-expansion-panel-text>
            </v-expansion-panel>
            <v-expansion-panel>
              <v-expansion-panel-title> Community </v-expansion-panel-title>
              <v-expansion-panel-text>
                <ul style="list-style-type: none; padding-left: 0">
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://community.amd.com/t5/support-forums/ct-p/supprtforums"
                      >Support</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://community.amd.com/t5/developers/ct-p/devgurus"
                      >Developer</a
                    >
                  </li>
                  <li>
                    <a href="https://community.amd.com/t5/red-team/ct-p/red-team"
                      >Red Team</a
                    >
                  </li>
                </ul>
              </v-expansion-panel-text>
            </v-expansion-panel>
            <v-expansion-panel>
              <v-expansion-panel-title> Partners </v-expansion-panel-title>
              <v-expansion-panel-text>
                <ul style="list-style-type: none; padding-left: 0">
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://www.amd.com/en/developer.html"
                      >Developers Center</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://www.amd.com/en/partner.html"
                      >AMD Partner Hub</a
                    >
                  </li>
                  <li>
                    <a
                      href="https://www.amd.com/en/corporate/university-program.html"
                      >AMD University Program</a
                    >
                  </li>
                </ul>
              </v-expansion-panel-text>
            </v-expansion-panel>
            <v-expansion-panel>
              <v-expansion-panel-title> Investors </v-expansion-panel-title>
              <v-expansion-panel-text>
                <ul style="list-style-type: none; padding-left: 0">
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://ir.amd.com/"
                      >Investor Relations</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://ir.amd.com/financial-information"
                      >Financial Information</a
                    >
                  </li>
                  <li>
                    <a
                      href="https://ir.amd.com/leadership-governance/board-of-directors"
                      >Board of Directors</a
                    >
                  </li>
                  <li>
                    <a
                      target="_blank"
                      rel="noopener noreferrer"
                      href="https://ir.amd.com/leadership-governance/governance-documents"
                      >Governance Documents</a
                    >
                  </li>
                  <li>
                    <a href="https://ir.amd.com/sec-filings">SEC Filings</a>
                  </li>
                </ul>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </v-col>
      </v-row>

      <!-- Footer Navigation Links -->
      <v-row style="display: flex; justify-content: center; padding: 30px">
        <div class="footer-links row">
          <div
            class="footer-column col-12 col-sm-12 col-md-12 mb-3"
            style="text-align: center"
          >
            <ul
              class="footer-nav"
              style="
                list-style: none;
                padding: 0px;
                display: flex;
                justify-content: center;
                flex-wrap: wrap;
              "
            >
              <li>
                <a
                  href="https://www.amd.com/en/legal/copyright.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  >Terms and Conditions
                </a>
              </li>
              <li class="fotter-pipe">|</li>
              <li>
                <a
                  href="https://www.amd.com/en/legal/privacy.html"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Privacy (Updated)</a
                >
              </li>
              <li class="fotter-pipe">|</li>
              <li>
                <a
                  href="https://www.amd.com/en/legal/trademarks.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  >Trademarks</a
                >
              </li>
              <li class="fotter-pipe">|</li>
              <li>
                <a
                  href="https://www.amd.com/content/dam/amd/en/documents/corporate/cr/supply-chain-transparency.pdf"
                  target="_blank"
                  rel="noopener noreferrer"
                  >Supply Chain Transparency</a
                >
              </li>
              <li class="fotter-pipe">|</li>
              <li>
                <a
                  href="https://www.amd.com/en/legal/competition.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  >Fair & Open Competition</a
                >
              </li>
              <li class="fotter-pipe">|</li>
              <li>
                <a
                  href="https://www.amd.com/content/dam/amd/en/documents/corporate/amd-uk-tax-strategy.pdf"
                  target="_blank"
                  rel="noopener noreferrer"
                  >UK Tax Strategy</a
                >
              </li>
              <li class="fotter-pipe">|</li>
              <li>
                <a
                  href="https://www.amd.com/en/legal/cookies.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  >Cookies Policy</a
                >
              </li>
              <li class="fotter-pipe">|</li>
              <li>
                <a href="#cookiessettings" role="button" class="ot-sdk-show-settings"
                  >Cookie Settings</a
                >
              </li>
            </ul>
          </div>
        </div>
      </v-row>

      <!-- Copyright -->
      <v-row>
        <div class="sba-copywrite">
          © {{ getCurrentYear }} Advanced Micro Devices, Inc.
        </div>
      </v-row>
      <v-row>
        <v-col style="padding: 20px"> </v-col>
      </v-row>
    </v-container>
  </v-footer>
</template>

<script>
import { defineComponent } from "vue";

export default defineComponent({
  name: "FooterBar",
  computed: {
    getCurrentYear() {
      return new Date().getFullYear();
    },
  },
});
</script>

<style scoped>
.footer-column {
  text-align: left;
}

.footer-sub-header {
  color: white;
  font-size: 18px;
  font-weight: 600;
  padding-bottom: 10px;
  font-family: "Titillium Web", Arial, sans-serif;
}

.fotter-class {
  line-height: 28px;
}

.fotter-class a {
  text-decoration: none;
  color: #7a7a7a;
  white-space: nowrap;
  font-size: 14px;
  font-family: "Titillium Web", Arial, sans-serif;
}

.fotter-class a:hover {
  text-decoration: underline !important;
  color: #fff !important;
}

.social-menu {
  display: flex;
  flex-wrap: nowrap;
  justify-content: flex-end;
}

.social-menu li {
  margin: 0.5rem;
}

.social-menu i {
  font-size: 1.0rem;
}

.footer-nav {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
}

.footer-nav li {
  white-space: nowrap;
}

.footer-nav a {
  text-decoration: none !important;
  color: #9d9fa2;
  font-family: "Titillium Web", Arial, sans-serif;
  font-size: 14px;
}

.footer-nav a:hover {
  text-decoration: underline !important;
  color: #fff !important;
}

.fotter-pipe {
  color: rgb(157, 159, 162);
  padding: 0 1vh;
}

.sba-copywrite {
  text-decoration: none;
  display: block;
  color: grey;
  font-family: 'Open sans', Arial, sans-serif;
  font-size: 13px;
  width: 100%;
  text-align: center;
}

/* Mobile expansion panel links */
.v-expansion-panel-text ul li a {
  text-decoration: none;
  color: grey;
}

.v-expansion-panel-text ul li a:hover {
  text-decoration: underline;
  color: #fff;
}

@media (max-width: 1480.98px) {
  .footer-nav {
    flex-wrap: wrap;
    font-size: 13px;
    justify-content: center;
  }
}

@media (min-width: 768px) {
  .social-menu i {
    font-size: 1.27rem;
  }
}

@media (max-width: 767.98px) {
  .footer-nav {
    flex-wrap: wrap;
    justify-content: center;
  }

  .footer-nav li {
    padding: 5px;
  }

  .fotter-pipe {
    padding-top: 5px !important;
  }

  .social-menu {
    justify-content: center;
    flex-wrap: wrap;
  }

  .social-menu i {
    font-size: 1rem;
  }

  .social-menu li {
    margin: 0.5rem;
  }
}
</style>

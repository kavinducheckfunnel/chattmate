/*
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

SetupView serves two jobs: first-run setup, and ongoing self-serve signup at
/signup.

This suite was rewritten when the view was. It previously asserted the
single-tenant behaviour — a "Welcome to ChatterMate" heading, a business-hours
grid, and a redirect to /ai-agents as soon as *any* organization existed. That
last one is the interesting case: once every visitor creates their own
workspace, redirecting on "an organization exists" makes signup unreachable for
everyone after the first customer. There is a test for exactly that below.
*/

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, VueWrapper, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import SetupView from '../../views/SetupView.vue'

vi.mock('timezone-select-js', () => ({
  listTz: () => [{ value: 'America/New_York', label: 'New York' }],
  clientTz: () => 'America/New_York',
}))

vi.mock('@/services/organization', () => ({
  createOrganization: vi.fn(),
  getSetupStatus: vi.fn().mockResolvedValue(false),
}))

const authed = { value: false }
vi.mock('@/services/user', () => ({
  userService: {
    isAuthenticated: () => authed.value,
    getCurrentUser: () => null,
  },
}))

vi.mock('@/services/firebase', () => ({
  messaging: {},
  requestNotificationPermission: vi.fn(),
}))

vi.mock('@/composables/useNotifications', () => ({
  useNotifications: vi.fn(() => ({
    requestPermission: vi.fn(),
    hasPermission: { value: false },
  })),
}))

import { createOrganization, getSetupStatus } from '@/services/organization'

const VALID = {
  name: 'Acme Inc',
  domain: 'acme.com',
  adminName: 'Alex Morgan',
  email: 'alex@acme.com',
  password: 'Str0ng!Passw0rd',
}

describe('SetupView', () => {
  let wrapper: VueWrapper
  let router: ReturnType<typeof createRouter>

  const mountView = async () => {
    wrapper = mount(SetupView, { global: { plugins: [router] } })
    // The onMounted status check is async, and the whole form is behind
    // `v-if="!checkingOrganization"` until it settles.
    await flushPromises()
    return wrapper
  }

  /** Fill the form the way a person would, so the input handlers run. */
  const fillValid = async (over: Partial<typeof VALID> = {}) => {
    const v = { ...VALID, ...over }
    await wrapper.find('#orgName').setValue(v.name)
    await wrapper.find('#domain').setValue(v.domain)
    await wrapper.find('#adminName').setValue(v.adminName)
    await wrapper.find('#adminEmail').setValue(v.email)
    await wrapper.find('#adminPassword').setValue(v.password)
    await wrapper.find('#confirmPassword').setValue(v.password)
  }

  const submit = async () => {
    await wrapper.find('form').trigger('submit')
    await flushPromises()
  }

  const errorText = () => wrapper.find('.auth-error').text()

  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    authed.value = false
    vi.mocked(getSetupStatus).mockResolvedValue(false)
    vi.mocked(createOrganization).mockResolvedValue({} as never)

    router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/login', component: { template: '<div />' } },
        { path: '/ai-agents', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    await mountView()
  })

  it('renders the signup form', () => {
    expect(wrapper.find('.auth-page').exists()).toBe(true)
    expect(wrapper.find('h1').text()).toBe('Create your workspace')
    expect(wrapper.find('#orgName').exists()).toBe(true)
    expect(wrapper.find('#domain').exists()).toBe(true)
    expect(wrapper.find('#adminEmail').exists()).toBe(true)
  })

  it('does not ask an anonymous visitor for the setup status at all', () => {
    // The check is gated on being signed in. Calling it anonymously is what the
    // old single-tenant flow did, and it is what led to the redirect below.
    expect(getSetupStatus).not.toHaveBeenCalled()
  })

  // The regression this suite exists for. Signup has to stay reachable for the
  // second customer and every one after.
  it('keeps signup reachable once an organization already exists', async () => {
    vi.mocked(getSetupStatus).mockResolvedValue(true)

    await mountView()

    expect(router.currentRoute.value.path).toBe('/')
    expect(wrapper.find('form').exists()).toBe(true)
  })

  it('sends a signed-in user to their workspace instead of signing up again', async () => {
    authed.value = true
    vi.mocked(getSetupStatus).mockResolvedValue(true)

    await mountView()

    expect(getSetupStatus).toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/ai-agents')
  })

  describe('validation', () => {
    it('rejects an invalid workspace name', async () => {
      await fillValid({ name: 'A' })
      await submit()
      expect(errorText()).toContain('workspace name')
      expect(createOrganization).not.toHaveBeenCalled()
    })

    it('rejects an invalid domain', async () => {
      await fillValid({ domain: 'not a domain' })
      await submit()
      expect(errorText()).toContain('domain')
      expect(createOrganization).not.toHaveBeenCalled()
    })

    it('rejects an invalid email', async () => {
      await fillValid({ email: 'alex@' })
      await submit()
      expect(errorText()).toContain('email')
      expect(createOrganization).not.toHaveBeenCalled()
    })

    // The UI checklist and the backend's validate_password_strength() enforce
    // the same rules. When they drifted, signup failed with a message that
    // contradicted the checklist the user had just satisfied.
    it('rejects a password that misses a policy requirement', async () => {
      await fillValid({ password: 'alllowercase' })
      await submit()
      expect(errorText()).toContain('requirements')
      expect(createOrganization).not.toHaveBeenCalled()
    })

    it('rejects mismatched confirmation', async () => {
      await fillValid()
      await wrapper.find('#confirmPassword').setValue('Different!Pass1')
      await submit()
      expect(errorText()).toContain('do not match')
      expect(createOrganization).not.toHaveBeenCalled()
    })
  })

  it('submits the collected workspace and owner details', async () => {
    await fillValid()
    await submit()

    expect(createOrganization).toHaveBeenCalledTimes(1)
    expect(vi.mocked(createOrganization).mock.calls[0][0]).toMatchObject({
      name: VALID.name,
      domain: VALID.domain,
      admin_name: VALID.adminName,
      admin_email: VALID.email,
      admin_password: VALID.password,
      timezone: 'America/New_York',
    })
    expect(router.currentRoute.value.path).toBe('/ai-agents')
  })

  // A hard-gated deployment creates the account but issues no session, so the
  // view must not pretend the user is signed in.
  it('shows the verify-your-email state instead of routing in', async () => {
    vi.mocked(createOrganization).mockResolvedValue({
      email_verification_required: true,
      email_verification_sent: true,
    } as never)

    await fillValid()
    await submit()

    expect(wrapper.find('h1').text()).toBe('Check your inbox')
    expect(wrapper.text()).toContain(VALID.email)
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('says so when the account exists but the email could not be sent', async () => {
    vi.mocked(createOrganization).mockResolvedValue({
      email_verification_required: true,
      email_verification_sent: false,
    } as never)

    await fillValid()
    await submit()

    expect(wrapper.text()).toContain("couldn't send the verification")
  })

  // axios puts "Request failed with status code 409" on the Error; the reason
  // the user needs is in response.data.detail.
  it('surfaces the API reason rather than the axios status text', async () => {
    vi.mocked(createOrganization).mockRejectedValue({
      response: { data: { detail: 'That email is already registered.' } },
    })

    await fillValid()
    await submit()

    expect(errorText()).toBe('That email is already registered.')
  })
})

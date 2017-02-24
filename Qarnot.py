from Deadline.Cloud import *
from Deadline.Scripting import *
from FranticX import Environment2

import qarnot
import random


######################################################################
# This is the function that Deadline calls to get an instance of the
# main CloudPluginWrapper class.
######################################################################

def GetCloudPluginWrapper():
    return QarnotPlugin()


######################################################################
# This is the function that Deadline calls when the cloud plugin is
# no longer in use so that it can get cleaned up.
######################################################################

def CleanupCloudPlugin(cloudPlugin):
    cloudPlugin.Cleanup()


######################################################################
# This is the main DeadlineCloudListener class for Qarnot.
######################################################################

class QarnotPlugin(CloudPluginWrapper):

    def __init__(self):
        self.conn = None
        self.startedInstances = []

        # Set up our callbacks for cloud control

        self.VerifyAccessCallback += self.VerifyAccess
        self.AvailableHardwareTypesCallback += self.GetAvailableHardwareTypes
        self.AvailableOSImagesCallback += self.GetAvailableOSImages
        self.CreateInstancesCallback += self.CreateInstances
        self.TerminateInstancesCallback += self.TerminateInstances
        self.CloneInstanceCallback += self.CloneInstance
        self.GetActiveInstancesCallback += self.GetActiveInstances
        self.StopInstancesCallback += self.StopInstances
        self.StartInstancesCallback += self.StartInstances
        self.RebootInstancesCallback += self.RebootInstances

        self.tempHardwareTypes = ['hardware']
        self.errorCredentials = 'Invalid credential'
        self.errorCluster = 'Invalid cluster'

        self.licenseServer = ''
        self.licenseMode = ''
        self.repository = ''
        self.proxyCrt = ''
        self.proxySSL = ''
        self.taskPrefix = 'deadline'
        self.resourcesBucket = 'deadline-input'
        self.resultsBucket = 'deadline-output'

    def Cleanup(self):
        del self.conn
        del self.startedInstances

        # Clean up our callbacks for cloud control

        del self.VerifyAccessCallback
        del self.AvailableHardwareTypesCallback
        del self.AvailableOSImagesCallback
        del self.CreateInstancesCallback
        del self.TerminateInstancesCallback
        del self.CloneInstanceCallback
        del self.GetActiveInstancesCallback
        del self.StopInstancesCallback
        del self.StartInstancesCallback
        del self.RebootInstancesCallback

    def RefreshConnection(self):
        """
        Refreshes our connection to Qarnot API
        """

        # API token
        token = self.GetConfigEntryWithDefault('Token', '')

        # Request API without certificate
        unsafe = self.GetConfigEntry('Unsafe')

        if len(token) <= 0:
            raise Exception(self.errorCredentials)

        # API cluster
        cluster = self.GetConfigEntryWithDefault('Cluster', '')

        if len(cluster) <= 0:
            raise Exception(self.errorCluster)

        # init connection to API
        self.conn = qarnot.connection.Connection(client_token=token,
                cluster_url=cluster, cluster_unsafe=unsafe)

######## CONFIGURATION #########################################################
        self.licenseServer = self.GetConfigEntryWithDefault('LicenceServer', '')
        self.licenseMode = self.GetConfigEntryWithDefault('LicenceMode', '')
        self.repository = self.GetConfigEntryWithDefault('Repository', '')
        self.proxyCrt = self.GetConfigEntryWithDefault('ProxyCrt', '')
        ssl = self.GetConfigEntryWithDefault('SSL', '')
        self.proxySSL = ssl
######## CONFIGURATION #########################################################

    def VerifyAccess(self):
        """
        verify if requests to Qarnot API are valid
        :return: True if valid
        """

        self.RefreshConnection()
        if self.conn is None:
            return False

        try:
            self.conn.user_info
        except:
            print('Error: Invalid credentials')
            return False

        return True

    def GetAvailableHardwareTypes(self):
        """
        :return: list of available HardwareTypes
        """

        try:
            hardwareList = []
            for hardwareType in self.tempHardwareTypes:
                ht = HardwareType()
                ht.ID = hardwareType
                ht.Name = hardwareType
                hardwareList.append(ht)

            return hardwareList
        except:
            raise Exception("Error : can't find hardware types")

    def GetAvailableOSImages(self):
        """
        :return: Return list of available OSImages
        supported by this provider : correspond to API profiles
        Must be implemented for the Balancer to work.

        TODO: get list of lumiere versions available in dwarf repo (docker)
            instead of qarnot deadline-* profiles.
        """

        if self.VerifyAccess() is False:
            raise Exception(self.errorCredentials)

        imageList = []
        images = self.conn.profiles()

        for image in images:

            # Use only profiles dedicated for deadline
            if self.taskPrefix in image.name:
                osi = OSImage()
                osi.ID = image.name
                osi.Description = image.name
                osi.Bitness = 64
                osi.Platform = Environment2.OS.Linux
                imageList.append(osi)

        return imageList

    @staticmethod
    def ConvertStatus(state):
        """
        convert Qarnot API states to deadline states
        :param state: state from Qarnot Task
        :return: state for deadline Instance
        """

        res = InstanceStatus.Unknown

        states = {
            'pending': ['PartiallyDispatched', 'FullyDispatched',
                        'UnSubmitted', 'Submitted'],
            'running': ['PartiallyExecuting', 'FullyExecuting'],
            'rebooting': [],
            'stopping': ['DownloadingResults'],
            'stopped': ['Cancelled', 'Success', 'Failure'],
            'terminated': [],
            }
        if state in states['pending']:
            res = InstanceStatus.Pending
        elif state in states['running']:
            res = InstanceStatus.Running
        elif state in states['rebooting']:
            res = InstanceStatus.Rebooting
        elif state in states['stopping']:
            res = InstanceStatus.Stopping
        elif state in states['stopped']:
            res = InstanceStatus.Stopped
        elif state in states['terminated']:
            res = InstanceStatus.Terminated

        return res

    def GetActiveInstances(self):
        """
        :return: list of CloudInstance objects that are currently active
        Corresponds to API tasks
        """

        activeInstances = []
        self.RefreshConnection()

        if self.conn is not None:
            tasks = self.conn.tasks()

            for task in tasks:

                # instances in API are tasks containing "deadline" somewhere in task.name
                if self.taskPrefix in task.name:
                    instance = CloudInstance()
                    instance.ID = task.uuid
                    instance.Name = task.name
                    instance.Provider = 'Qarnot'
                    instance.Status = self.ConvertStatus(task.state)
                    instance.Hostname = self.conn.cluster
                    instance.ImageID = task.profile

                    # instance.PublicIP =
                    # instance.PrivateIP =
                    # instance.HardwareID =
                    # instance.Zone =

                    activeInstances.append(instance)
        else:
            raise Exception(self.errorCredentials)

        return activeInstances

    def CreateInstances(
        self,
        hardwareID,
        imageID,
        count,
        ):
        """
        Start instances and return list of CloudInstance objects that
        have been started.
        Must be implemented for the Balancer to work.
        Corresponds to API task create and submit
        """

        startedIDs = []
        self.RefreshConnection()

        if self.VerifyAccess() is False:
            raise Exception(self.errorCredentials)

        # TODO : use profile deadline and specify docker repo with imageID
        profile = imageID

        # is random name good enough for uniqueness?
        def r():
            return random.randint(0, 255)

        for i in range(count):
            rand = '-%02X%02X%02X' % (r(), r(), r())  # use a name with random 3byte hex value

            # name form: deadline-<profile>-<random>
            # name = self.taskPrefix + "-" + profile + rand
            name = profile + rand
            task = self.conn.create_task(name, profile, 1)
            bucketOut = self.conn.create_bucket(self.resultsBucket)
            bucketIn = self.conn.create_bucket(self.resourcesBucket)
            task.results = bucketOut
            task.resources = [bucketIn]

            instance = CloudInstance()
            instance.Name = task.name
            instance.ImageID = imageID
            instance.task = task

            instance.task.constants['DEADLINE_REPOSITORY'] = self.repository
            instance.task.constants['DEADLINE_SSL'] = self.proxySSL
            instance.task.constants['DEADLINE_LICENSE_MODE'] = self.licenseMode
            instance.task.constants['DEADLINE_LICENSE_SERVER'] = \
                self.licenseServer
            instance.task.constants['DEADLINE_CRT'] = \
                ''.join(self.proxyCrt.splitlines())

            # instance.task.constants['DOCKER_HOST'] = instance.Name
            # instance.task.constants['DOCKER_TAG'] = "2.100.106"

            instance.task.submit()
            instance.ID = task.uuid
            startedIDs.append(instance)
            self.startedInstances.append(instance)

        # self.StartInstances(startedIDs)
        return startedIDs

    def TerminateInstances(self, instanceIDs):

        # TODO: Return list of boolean values indicating which instances
        # terminated successfully.
        # Must be implemented for the Balancer to work.
        if instanceIDs is None or len(instanceIDs) == 0:
            return []

        results = [False] * len(instanceIDs)
        self.RefreshConnection()

        if self.VerifyAccess() is False:
            raise Exception(self.errorCredentials)

        terminatedIDs = []
        for instanceID in instanceIDs:
            try:
                task = self.conn.retrieve_task(instanceID)
                task.delete(False, False)
                terminatedIDs.append(task.uuid)
            except:
                print 'Error terminating Instance'

        for i in range(0, len(instanceIDs)):
            instanceID = instanceIDs[i]
            if instanceID in terminatedIDs:
                results[i] = True

        return results

    def StopInstances(self, instanceIDs):

        # TODO: Return list of boolean values indicating which instances
        # stopped successfully.
        if instanceIDs is None or len(instanceIDs) == 0:
            return []

        results = [False] * len(instanceIDs)
        self.RefreshConnection()

        if self.VerifyAccess() is False:
            raise Exception(self.errorCredentials)

        stoppedIDs = []
        for instanceID in instanceIDs:
            try:
                task = self.conn.retrieve_task(instanceID)
                task.abort()
                stoppedIDs.append(task.uuid)
            except:
                print 'Error stopping instance'

        for i in range(0, len(instanceIDs)):
            instanceID = instanceIDs[i]
            if instanceID in stoppedIDs:
                results[i] = True

        return results

    def StartInstances(self, instanceIDs):

        # TODO: Return list of boolean values indicating which instances
        # started successfully.
        if instanceIDs is None or len(instanceIDs) == 0:
            return []

        results = [False] * len(instanceIDs)
        self.RefreshConnection()
        for instanceID in instanceIDs:
            try:
                old_task = self.conn.retrieve_task(instanceID)
                instance = CloudInstance()
                instance.Name = old_task.name
                instance.ImageID = old_task.profile
                instance.task = old_task
                old_task.update()

                instance.task.constants['DEADLINE_REPOSITORY'] = self.repository
                instance.task.constants['DEADLINE_SSL'] = self.proxySSL
                instance.task.constants['DEADLINE_LICENSE_MODE'] = \
                    self.licenseMode
                instance.task.constants['DEADLINE_LICENSE_SERVER'] = \
                    self.licenseServer
                instance.task.constants['DEADLINE_CRT'] = \
                    ''.join(self.proxyCrt.splitlines())

                # instance.task.constants['DOCKER_HOST'] = instance.Name
                # instance.task.constants['DOCKER_TAG'] = "2.100.106"
                # instance.task.resources(old_task.resources)

                old_task.delete(False, False)
                instance.task.submit()
            except:
                # self.startedInstances.append(instance)
                print 'Error starting Instance'

        return results

    def RebootInstances(self, instanceIDs):

        # TODO: Return list of boolean values indicating which instances
        # rebooted successfully.
        if instanceIDs is None or len(instanceIDs) == 0:
            return []

        results = []
        self.RefreshConnection()
        for instanceID in instanceIDs:
            try:
                old_task = self.conn.retrieve_task(instanceID)
                instance = CloudInstance()
                instance.Name = old_task.name
                instance.ImageID = old_task.profile
                instance.task = old_task
                bucketOut = self.conn.create_bucket(self.resultsBucket)
                bucketIn = self.conn.create_bucket(self.resourcesBucket)
                instance.task.results = bucketOut
                instance.task.resources = [bucketIn]

                instance.task.constants['DEADLINE_REPOSITORY'] = self.repository
                instance.task.constants['DEADLINE_SSL'] = self.proxySSL
                instance.task.constants['DEADLINE_LICENSE_MODE'] = \
                    self.licenseMode
                instance.task.constants['DEADLINE_LICENSE_SERVER'] = \
                    self.licenseServer
                instance.task.constants['DEADLINE_CRT'] = \
                    ''.join(self.proxyCrt.splitlines())

                # instance.task.constants['DOCKER_HOST'] = instance.Name
                # instance.task.constants['DOCKER_TAG'] = "2.100.106"
                # instance.task.resources(old_task.resources)

                old_task.delete(False, False)
                instance.task.submit()
                results.append(instance)
            except:
                print 'Error rebooting Instance'

        return results

    def CloneInstance(self, instance, count):
        clonedIDs = []
        self.RefreshConnection()

        def r():
            return random.randint(0, 255)

        for i in range(0, count):
            try:
                rand = '-%02X%02X%02X' % (r(), r(), r())  # use a name with random 3byte hex value
                pr = instance.ImageID.encode('ascii', 'ignore')

                name = pr + rand
                taskCloned = self.conn.create_task(name, pr, 1)

                bucketOut = self.conn.create_bucket(self.resultsBucket)
                bucketIn = self.conn.create_bucket(self.resourcesBucket)
                task.results = bucketOut
                task.resources = [bucketIn]

                cloneInstance = CloudInstance()
                cloneInstance.Name = name
                cloneInstance.ImageID = pr
                cloneInstance.task = taskCloned

                cloneInstance.task.constants['DEADLINE_REPOSITORY'] = \
                    self.repository
                cloneInstance.task.constants['DEADLINE_SSL'] = \
                    self.proxySSL
                cloneInstance.task.constants['DEADLINE_LICENSE_MODE'] = \
                    self.licenseMode
                cloneInstance.task.constants['DEADLINE_LICENSE_SERVER'
                        ] = self.licenseServer
                cloneInstance.task.constants['DEADLINE_CRT'] = \
                    ''.join(self.proxyCrt.splitlines())

                # cloneInstance.task.constants['DOCKER_HOST'] = cloneInstance.Name
                # cloneInstance.task.constants['DOCKER_TAG'] = "2.100.106"
                cloneInstance.task.submit()
                cloneInstance.ID = cloneInstance.task.uuid
                clonedIDs.append(cloneInstance.ID)
            except:
                print 'Error Cloning Instance'

        return clonedIDs

import datetime
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from lrs import models
from lrs.exceptions import IDNotFoundError, ParamError
from lrs.util import etag, get_user_from_auth, log_message, update_parent_log_status, uri
import logging
import pdb
import json

logger = logging.getLogger('user_system_actions')

class ActivityProfile():
    def __init__(self, log_dict=None):
        self.log_dict = log_dict

    def post_profile(self, request_dict):
        post_profile = request_dict['profile']
        
        profile_id = request_dict['params']['profileId']
        if not uri.validate_uri(profile_id):
            err_msg = 'Profile ID %s is not a valid URI' % profile_id
            log_message(self.log_dict, err_msg, __name__, self.post_profile.__name__, True) 
            update_parent_log_status(self.log_dict, 400)       
            raise ParamError(err_msg)

        # get / create  profile
        p, created = models.activity_profile.objects.get_or_create(activityId=request_dict['params']['activityId'],  profileId=request_dict['params']['profileId'])
        if created:
            log_message(self.log_dict, "Created Activity Profile", __name__, self.post_profile.__name__)
            profile = ContentFile(post_profile)
        else:
            #   merge, update hash, save
            original_profile = json.load(p.profile)
            post_profile = json.loads(post_profile)
            log_message(self.log_dict, "Found a profile. Merging the two profiles.", __name__, self.post_profile.__name__)
            merged = dict(original_profile.items() + post_profile.items())
            # delete original one
            p.profile.delete()
            # update
            profile = ContentFile(json.dumps(merged))

        self.save_profile(p, created, profile, request_dict)

	#Save profile to desired activity
    def put_profile(self, request_dict):
        #Parse out profile from request_dict
        try:
            profile = ContentFile(request_dict['profile'].read())
        except:
            try:
                profile = ContentFile(request_dict['profile'])
            except:
                profile = ContentFile(str(request_dict['profile']))

        profile_id = request_dict['params']['profileId']
        if not uri.validate_uri(profile_id):
            err_msg = 'Profile ID %s is not a valid URI' % profile_id
            log_message(self.log_dict, err_msg, __name__, self.put_profile.__name__, True) 
            update_parent_log_status(self.log_dict, 400)
            raise ParamError(err_msg)

        #Get the profile, or if not already created, create one
        p,created = models.activity_profile.objects.get_or_create(profileId=request_dict['params']['profileId'],activityId=request_dict['params']['activityId'])
        
        if created:
            log_message(self.log_dict, "Created Activity Profile", __name__, self.put_profile.__name__)
        else:
            #If it already exists delete it
            etag.check_preconditions(request_dict,p, required=True)
            p.profile.delete()
            log_message(self.log_dict, "Retrieved Activity Profile", __name__, self.put_profile.__name__)
        self.save_profile(p, created, profile, request_dict)

    def save_profile(self, p, created, profile, request_dict):
        #Save profile content type based on incoming content type header and create etag
        p.content_type = request_dict['headers']['CONTENT_TYPE']
        p.etag = etag.create_tag(profile.read())
        
        #Set updated
        if 'headers' in request_dict and ('updated' in request_dict['headers'] and request_dict['headers']['updated']):
            p.updated = request_dict['headers']['updated']
        
        #Go to beginning of file
        profile.seek(0)
        
        #If it didn't exist, save it
        if created:
            p.save()

        #Set filename with the activityID and profileID and save
        fn = "%s_%s" % (p.activityId,request_dict.get('filename', p.id))
        p.profile.save(fn, profile)

        log_message(self.log_dict, "Saved Activity Profile", __name__, self.save_profile.__name__)

    def get_profile(self, profileId, activityId):
        log_message(self.log_dict, "Getting profile with profile id: %s -- activity id: %s" % (profileId, activityId),
            __name__, self.get_profile.__name__)

        #Retrieve the profile with the given profileId and activity
        try:
            return models.activity_profile.objects.get(profileId=profileId, activityId=activityId)
        except models.activity_profile.DoesNotExist:
            err_msg = 'There is no profile associated with the id: %s' % profileId
            log_message(self.log_dict, err_msg, __name__, self.get_profile.__name__, True)
            update_parent_log_status(self.log_dict, 404)
            raise IDNotFoundError(err_msg)


    def get_profile_ids(self, activityId, since=None):
        ids = []

        #If there is a since param return all profileIds since then
        if since:
            try:
                # this expects iso6801 date/time format "2013-02-15T12:00:00+00:00"
                profs = models.activity_profile.objects.filter(updated__gte=since, activityId=activityId)
            except ValidationError:
                err_msg = 'Since field is not in correct format'
                log_message(self.log_dict, err_msg, __name__, self.get_profile_ids.__name__, True) 
                update_parent_log_status(self.log_dict, 400)          
                raise ParamError(err_msg) 
            ids = [p.profileId for p in profs]
        else:
            #Return all IDs of profiles associated with this activity b/c there is no since param
            ids = models.activity_profile.objects.filter(activityId=activityId).values_list('profileId', flat=True)
        return ids

    def delete_profile(self, request_dict):
        #Get profile and delete it
        try:
            prof = self.get_profile(request_dict['params']['profileId'], request_dict['params']['activityId'])
            prof.delete()
        except models.activity_profile.DoesNotExist:
            pass #we don't want it anyway
        except IDNotFoundError:
            pass

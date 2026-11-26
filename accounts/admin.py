from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import ApprovedAdmin, Profile
from .services.account_service import AccountService
from .services.exceptions import AccountError

User = get_user_model()


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = ("role", "agency", "display_name", "firebase_uid")
    readonly_fields = ("agency", "display_name", "firebase_uid")
    help_text = "Promote a User to Scheduler here. Admins are managed under Approved admins."


# Replace django.contrib.auth's default User admin.
if admin.site.is_registered(User):
    admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ("email", "role", "agency", "is_active", "last_login")
    list_filter = ("profile__role", "profile__agency", "is_active")
    search_fields = ("email", "profile__display_name")
    ordering = ("email",)
    # Passwords live in Firebase; hide Django's password and permission fields.
    fieldsets = ((None, {"fields": ("email", "is_active", "last_login", "date_joined")}),)
    readonly_fields = ("email", "last_login", "date_joined")

    def has_add_permission(self, request):
        # Accounts are created by signing in with Firebase, or by the
        # provisioning command / Approved admins.
        return False

    @admin.display(ordering="profile__role")
    def role(self, obj):
        return obj.profile.get_role_display() if hasattr(obj, "profile") else "-"

    @admin.display(ordering="profile__agency")
    def agency(self, obj):
        return obj.profile.agency if hasattr(obj, "profile") else "-"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        AccountService.sync_role_flags(form.instance)


@admin.register(ApprovedAdmin)
class ApprovedAdminAdmin(admin.ModelAdmin):
    list_display = ("email", "approved_by", "created_at")
    fields = ("email",)
    search_fields = ("email",)

    def has_change_permission(self, request, obj=None):
        return False  # add or delete only

    def save_model(self, request, obj, form, change):
        try:
            _, link = AccountService.provision_admin(obj.email, approved_by=request.user)
        except AccountError as exc:
            # Keep the approval; the Firebase account can be finished later.
            obj.approved_by = request.user
            obj.save()
            messages.warning(
                request,
                f"{obj.email} is approved, but the sign-in account could not be created "
                f"({exc.message}) Run `manage.py create_admin {obj.email}` to finish.",
            )
            return
        obj.pk = ApprovedAdmin.objects.get(email=obj.email).pk
        messages.success(
            request,
            f"{obj.email} is approved. Send this one-time link to the new admin so they "
            f"can set a password (expires in about 1 hour): {link}",
        )

    def delete_model(self, request, obj):
        if obj.email == request.user.email:
            messages.error(request, "You cannot revoke your own admin approval.")
            return
        AccountService.revoke_admin(obj.email)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)

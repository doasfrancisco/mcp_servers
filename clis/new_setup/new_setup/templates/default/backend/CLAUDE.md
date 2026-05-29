# Backend rules

1. Never run `python manage.py makemigrations` yourself — I run it manually. Never hand-edit or hand-write migration files either.

2. Never change model attributes, add new relations (ForeignKey/OneToOne/ManyToMany), or create new models unless I explicitly tell you to. This includes renaming fields, changing field types/options, adding/removing fields on existing models, adding/removing relations, and introducing new Django model classes. If a task seems to require any of these, stop and ask first.

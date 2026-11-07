"""Modèle Pydantic de la logistique d'une course, rempli par Linkup (sortie structurée)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BibPickup(BaseModel):
    location: str | None = Field(None, description="Lieu exact du retrait des dossards (nom + adresse)")
    days: list[str] = Field(default_factory=list, description="Jours de retrait au format ISO AAAA-MM-JJ")
    hours: str | None = Field(None, description="Horaires de retrait, ex. 'samedi 10h-19h'")
    same_day_possible: bool | None = Field(None, description="Retrait possible le matin de la course")


class RequiredDocuments(BaseModel):
    pps: bool | None = Field(None, description="Parcours Prévention Santé (PPS) accepté ou exigé pour les non-licenciés")
    medical_certificate: bool | None = Field(None, description="Certificat médical exigé pour les non-licenciés")
    license_accepted: bool | None = Field(None, description="Licence FFA (ou fédération) acceptée à la place")
    notes: str | None = Field(None, description="Précisions du règlement sur les documents")


class Source(BaseModel):
    url: str
    title: str | None = None


class RaceLogistics(BaseModel):
    name: str = Field(..., description="Nom officiel de la course et de l'édition")
    edition_year: int | None = Field(None, description="Année de l'édition trouvée")
    date: str | None = Field(None, description="Date de la course, format ISO AAAA-MM-JJ")
    distance_km: float | None = Field(None, description="Distance de l'épreuve principale en km")
    start_time: str | None = Field(None, description="Heure de départ de l'épreuve principale, format HH:MM")
    start_location: str | None = Field(None, description="Lieu exact du départ (rue, place, ville)")
    city: str | None = Field(None, description="Ville du départ")
    country: str | None = None
    bib_pickup: BibPickup = Field(default_factory=BibPickup)
    start_access: str | None = Field(None, description="Accès au départ : métro, train, parking, navettes")
    required_documents: RequiredDocuments = Field(default_factory=RequiredDocuments)
    aid_stations: str | None = Field(None, description="Ravitaillements : nombre et kilomètres")
    time_limit: str | None = Field(None, description="Temps limite / barrière horaire, ex. '6h00'")
    registration_platform: str | None = Field(None, description="Plateforme d'inscription : Njuko, Klikego, site organisateur...")
    registration_url: str | None = Field(None, description="URL directe de la page d'inscription")
    price_eur: float | None = Field(None, description="Prix actuel de l'inscription en euros")
    registration_status: Literal["ouvert", "complet", "inconnu"] = Field(
        "inconnu", description="ouvert si l'inscription est possible aujourd'hui, complet si sold out, sinon inconnu"
    )
    official_url: str | None = Field(None, description="URL du site officiel de la course")
    regulation_url: str | None = Field(None, description="URL du règlement (page ou PDF)")
    sources: list[Source] = Field(default_factory=list)


class OpenRace(BaseModel):
    name: str
    date: str | None = Field(None, description="ISO AAAA-MM-JJ")
    city: str | None = None
    distance_km: float | None = None
    platform: str | None = Field(None, description="njuko ou klikego")
    registration_url: str | None = None
    price_eur: float | None = None


class OpenRaceList(BaseModel):
    races: list[OpenRace] = Field(default_factory=list)
